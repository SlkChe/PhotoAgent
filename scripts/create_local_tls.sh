#!/bin/bash
# Выпуск локального CA и отдельных сертификатов Dev/Stage без вывода ключей.
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
tls_root=".devsec/ssl"
mkdir -p "$tls_root/ca" "$tls_root/dev" "$tls_root/stage"
chmod 700 .devsec "$tls_root" "$tls_root/ca" "$tls_root/dev" "$tls_root/stage"

for tls_file in ca/ca.key ca/ca.crt dev/server.key dev/server.crt stage/server.key stage/server.crt; do
    if test -e "$tls_root/$tls_file"; then
        echo "Существующий комплект не перезаписывается: $tls_root/$tls_file" >&2
        exit 1
    fi
done

openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$tls_root/ca/ca.key"
openssl req -new -x509 -sha256 -days 1825 \
    -key "$tls_root/ca/ca.key" -out "$tls_root/ca/ca.crt" \
    -subj "/CN=PhotoAgent Local Development CA" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign"

for tls_env in dev stage; do
    tls_name="photoagent-${tls_env}.home.arpa"
    tls_dir="$tls_root/$tls_env"
    openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$tls_dir/server.key"
    openssl req -new -sha256 -key "$tls_dir/server.key" \
        -out "$tls_dir/server.csr" -subj "/CN=$tls_name"
    cat > "$tls_dir/extensions.cnf" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature
extendedKeyUsage=serverAuth
subjectAltName=DNS:$tls_name
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid,issuer
EOF
    openssl x509 -req -sha256 -days 90 -in "$tls_dir/server.csr" \
        -CA "$tls_root/ca/ca.crt" -CAkey "$tls_root/ca/ca.key" \
        -set_serial "0x$(openssl rand -hex 16)" -extfile "$tls_dir/extensions.cnf" \
        -out "$tls_dir/server.crt"
    openssl verify -CAfile "$tls_root/ca/ca.crt" -verify_hostname "$tls_name" \
        -purpose sslserver "$tls_dir/server.crt"
done
echo "Публичный CA для настройки доверия: $tls_root/ca/ca.crt"
openssl x509 -in "$tls_root/ca/ca.crt" -noout -sha256 -fingerprint
