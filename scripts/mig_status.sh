#! /bin/bash
RESET="\e[0m"
kubectl get nodes -o json > tmp.json

jq -c '.items[]' tmp.json | while read -r obj; do
    name=$(jq -r '.metadata.annotations["cluster.x-k8s.io/machine"]' <<< "$obj")
    mig_config=$(jq -r '.metadata.labels["nvidia.com/mig.config"]' <<< "$obj")
    mig_status=$(jq -r '.metadata.labels["nvidia.com/mig.config.state"]' <<< "$obj" )
    if [[ -n "$mig_config" && "$mig_config" != "null" ]]; then
      if [[ $mig_status == *"success"* ]]; then
        COLOUR="\e[32m"
      elif [[ $mig_status == *"pending"* ]]; then
        COLOUR="\e[33m"
      else
        COLOUR="\e[31m"
      fi
        echo "--------------------------------"
        echo -e "Name: $name"
        echo    -e "MIG config: $mig_config"
        echo    -e "Status: ${COLOUR}$mig_status${RESET}"
    fi
done
echo "--------------------------------"