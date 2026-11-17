#!/usr/bin/env bash
# Crea la instancia EC2 del central (D24) con su grupo de seguridad y su IP elástica, y
# deja impreso el comando para prepararla. Se puede correr varias veces: busca cada
# recurso por la etiqueta Name y solo crea lo que falta.
#
#   AWS_PROFILE=… LLAVE_PUBLICA=~/.ssh/central-dsp.pub despliegue/crear-ec2.sh
#
# Variables opcionales:
#   NOMBRE=central-dsp     etiqueta Name de todos los recursos
#   TIPO=t3.small          tipo de instancia (x86, como el portátil)
#   DISCO_GB=16            disco gp3 cifrado
#   SUBRED=subnet-…        subred pública; si falta, la VPC por defecto de la región
#   DOMINIO=dsp.cshire.io  si su zona está en Route 53 de la misma cuenta, se crea el A
set -euo pipefail

NOMBRE="${NOMBRE:-central-dsp}"
TIPO="${TIPO:-t3.small}"
DISCO_GB="${DISCO_GB:-16}"
DOMINIO="${DOMINIO:-dsp.cshire.io}"
LLAVE_PUBLICA="${LLAVE_PUBLICA:?falta LLAVE_PUBLICA: la ruta de la llave pública SSH}"
AMI_PARAMETRO=/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id

aws() { command aws --output text "$@"; }
paso() { printf '\n==> %s\n' "$*"; }
etiquetas() { echo "ResourceType=$1,Tags=[{Key=Name,Value=$NOMBRE},{Key=Proyecto,Value=$NOMBRE}]"; }

# Agrega una regla de entrada; si ya existe, no hace nada. Cualquier otro error detiene.
abrir() {
  local salida
  if ! salida=$(aws ec2 authorize-security-group-ingress --group-id "$SG" --ip-permissions "$1" 2>&1); then
    grep -q InvalidPermission.Duplicate <<<"$salida" || { echo "$salida" >&2; exit 1; }
  fi
}

paso "Cuenta y región"
aws sts get-caller-identity --query Arn
REGION=$(command aws configure get region || true)
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-$REGION}}"
[ -n "$REGION" ] || { echo "Falta la región: AWS_REGION o la del perfil." >&2; exit 1; }
echo "$REGION"

paso "Red"
if [ -n "${SUBRED:-}" ]; then
  VPC=$(aws ec2 describe-subnets --subnet-ids "$SUBRED" --query 'Subnets[0].VpcId')
else
  VPC=$(aws ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId')
  [ "$VPC" != "None" ] || { echo "La región no tiene VPC por defecto: indica SUBRED=subnet-… (pública)." >&2; exit 1; }
fi
echo "VPC $VPC${SUBRED:+, subred $SUBRED}"

paso "Llave SSH $NOMBRE"
if ! aws ec2 describe-key-pairs --key-names "$NOMBRE" >/dev/null 2>&1; then
  aws ec2 import-key-pair --key-name "$NOMBRE" --public-key-material "fileb://$LLAVE_PUBLICA" \
    --tag-specifications "$(etiquetas key-pair)" >/dev/null
fi
aws ec2 describe-key-pairs --key-names "$NOMBRE" --query 'KeyPairs[0].[KeyName,KeyFingerprint]'

paso "Grupo de seguridad $NOMBRE: 80 y 443 para todos, 22 solo desde esta IP"
SG=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=$NOMBRE" "Name=vpc-id,Values=$VPC" \
  --query 'SecurityGroups[0].GroupId')
if [ "$SG" = "None" ]; then
  SG=$(aws ec2 create-security-group --group-name "$NOMBRE" --vpc-id "$VPC" \
    --description "Servidor central DSP: HTTP y HTTPS publicos, SSH del operador" \
    --tag-specifications "$(etiquetas security-group)" --query GroupId)
fi
MI_IP=$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')
for puerto in 80 443; do
  abrir "IpProtocol=tcp,FromPort=$puerto,ToPort=$puerto,IpRanges=[{CidrIp=0.0.0.0/0}],Ipv6Ranges=[{CidrIpv6=::/0}]"
done
abrir "IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=$MI_IP/32,Description=operador}]"
echo "$SG (SSH desde $MI_IP)"

paso "Instancia $NOMBRE ($TIPO, Ubuntu 24.04)"
ID=$(aws ec2 describe-instances --filters "Name=tag:Name,Values=$NOMBRE" \
  "Name=instance-state-name,Values=pending,running,stopping,stopped" \
  --query 'Reservations[0].Instances[0].InstanceId')
if [ "$ID" = "None" ]; then
  AMI=$(aws ssm get-parameter --name "$AMI_PARAMETRO" --query Parameter.Value)
  ID=$(aws ec2 run-instances --image-id "$AMI" --instance-type "$TIPO" --key-name "$NOMBRE" \
    --security-group-ids "$SG" ${SUBRED:+--subnet-id "$SUBRED"} \
    --block-device-mappings "DeviceName=/dev/sda1,Ebs={VolumeSize=$DISCO_GB,VolumeType=gp3,Encrypted=true,DeleteOnTermination=true}" \
    --metadata-options HttpTokens=required,HttpPutResponseHopLimit=1,HttpEndpoint=enabled \
    --tag-specifications "$(etiquetas instance)" "$(etiquetas volume)" \
    --query 'Instances[0].InstanceId')
  echo "creada $ID con $AMI"
fi
estado=$(aws ec2 describe-instances --instance-ids "$ID" --query 'Reservations[0].Instances[0].State.Name')
[ "$estado" = "stopped" ] && aws ec2 start-instances --instance-ids "$ID" >/dev/null
aws ec2 wait instance-running --instance-ids "$ID"
echo "$ID corriendo"

paso "IP elástica"
ASIGNACION=$(aws ec2 describe-addresses --filters "Name=tag:Name,Values=$NOMBRE" --query 'Addresses[0].AllocationId')
if [ "$ASIGNACION" = "None" ]; then
  ASIGNACION=$(aws ec2 allocate-address --domain vpc --tag-specifications "$(etiquetas elastic-ip)" --query AllocationId)
fi
aws ec2 associate-address --allocation-id "$ASIGNACION" --instance-id "$ID" --allow-reassociation >/dev/null
IP=$(aws ec2 describe-addresses --allocation-ids "$ASIGNACION" --query 'Addresses[0].PublicIp')
echo "$IP"

paso "DNS: $DOMINIO → $IP"
RAIZ="${DOMINIO#*.}"
ZONA=$(aws route53 list-hosted-zones-by-name --dns-name "$RAIZ." \
  --query "HostedZones[?Name=='$RAIZ.' && Config.PrivateZone==\`false\`].Id | [0]" 2>/dev/null || echo None)
if [ -n "$ZONA" ] && [ "$ZONA" != "None" ]; then
  aws route53 change-resource-record-sets --hosted-zone-id "$ZONA" --change-batch \
    "{\"Changes\":[{\"Action\":\"UPSERT\",\"ResourceRecordSet\":{\"Name\":\"$DOMINIO.\",\"Type\":\"A\",\"TTL\":60,\"ResourceRecords\":[{\"Value\":\"$IP\"}]}}]}" \
    --query ChangeInfo.Status
else
  echo "La zona $RAIZ no está en Route 53 de esta cuenta: crea a mano el registro A $DOMINIO → $IP, sin proxy."
fi

paso "Siguiente paso"
cat <<SIGUIENTE
ssh -i <llave privada> ubuntu@$IP 'ADMIN_TOKEN=… bash -s' < despliegue/preparar-vm.sh
SIGUIENTE
