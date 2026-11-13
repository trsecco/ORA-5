#!/bin/sh
# Atualiza a versão do app (index.html + version.json) antes de cada publicação
V=$(date +%Y%m%d%H%M)
sed -i "s/const APP_V=\"[0-9]*\"/const APP_V=\"$V\"/" index.html
echo "{\"v\":\"$V\"}" > version.json
echo "$V"
