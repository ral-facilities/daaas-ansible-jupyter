
# Ansible JupyterHub Server with Prometheus Stacks for STFC Cloud Openstacks
Provides a JupyterHub Service on an existing Openstack Cluster. This uses the helm chart provided by [ZeroToJupyterHub](https://github.com/jupyterhub/zero-to-jupyterhub-k8s).
## Contents
- [Features](#features)
- [Limitations](#limitations)
- [Requirements](#requirements)
  * [Local Environment Setup](#local-environment-setup)
- [Deploying JupyterHub](#deploying-jupyterhub)
  * [Instructions](#instructions)
- [Customising your jupyterhub deployment](#Customising-your-jupyterhub-deployment)
  * [HTTPS Config](#HTTPS-Config)
  * [SSL Setup](#SSL-Setup)
  * [Note on Renewal Limits](#Note-on-Renewal-Limits)
- [Maintenance and Notes](#Maintenance-and-Notes)
    * [Single hub instance](#Single-hub-instance)
    * [Autoscaler](#Autoscaler)
    * [Proxy_public service notes](#Proxy_public-service-notes)
    * [Longhorn](#Longhorn)


## Features

- Longhorn Support
- Multiple profiles for different resource limits
- Automatic HTTPS support, can have a instance up in <1 hour (with pre-requisites in place)

## Limitations

- The primary worker/master flavour cannot be changed after creation
- Cannot use placeholders for optional profiles (e.g. GPU placeholder)
- Some metrics can't be selected by node name in Grafana dashboard as it requires a reverse DNS.

## Requirements
The following assumes you have an Ubuntu 22.04 or 24.04 machine with `pip3`, `python3` already installed.

- Ansible ([Installing Ansible — Ansible Documentation](https://docs.ansible.com/ansible/latest/installation_guide/intro_installation.html)) - on Ubuntu run `apt install ansible`.
- Helm 3 ([Installing Helm](https://helm.sh/docs/intro/install/))
- kubectl ([Install Tools | Kubernetes](https://kubernetes.io/docs/tasks/tools/))

Helm and kubectl can be installed using snap:

```bash
sudo apt-get update && sudo apt-get install -y snapd
export PATH=$PATH:/snap/bin
sudo snap install kubectl --classic
sudo snap install helm --classic
```

## Deploying JupyterHub

### Instructions

1. Deploy a capi cluster
2. Ensure that you can access the cluster from the machine you are running this playbook from (`kubectl get nodes`)
3. git clone this repo (`git clone https://github.com/stfc/ansible-jupyter`)
4. Install Ansible requirements `ansible-galaxy collection install -r requirements.yml`
5. Uncomment the correct line for your environment in `inventory/hosts`
6. Fill in the variables for your given environment in `group_vars/<environment>/all.yaml`
    - `iris_iam`: If true uses iris iam groups for admin and user accounts, if false uses jupyterhub deployed accounts instead
    - `client_id`: Client ID from iris iam
    - `client_secret`: Client secret from iris iam
    - `admin_groups`: List of iris iam groups to use for admins
    - `allowed_groups`: List of allowed iris iam groups to use for users
      </p>
    - `admin_names`: The admin usernames to be created (these will be prepended with `admin-`)
    - `number_of_users`: The number of user accounts to be created
    - `username`: Username style to use (these with have numbers added to the end)
      </p>
    - `display_name`: The name of the environment displayed to the user
    - `description`: The description of the environment displayed to the user
    - `default`: Whether the environment is the default environment or not
    - `image`: The image to use for generating the environment
    - `gpu_required`: If a GPU is required for this profile
    - `commands`: List of commands (git clones) to run on the deployed instances/images
      </p>
    - `iris_iam`: Detials for setting up iris-iam
      - `required`: If iris-iam is required or not
      - `client_id`: Client ID from iris iam
      - `client_secret`: Client secret from iris iam
      - `admin_groups`: List of iris iam groups to use for admins
      - `allowed_groups`: List of allowed iris iam groups to use for users

6. Make sure kubeconfig is in ~/.kube
7. Run the playbook and pass in name of the kubeconfig filename (without extnsion) and the deployment version: 
`ansible-playbook deploy_jhub.yml -e "cluser_name=kubeconfig-name" -e "env=dev-or-prod-or-training"`

## Customising your jupyterhub deployment
These are settings/variables to chagne/add to customise your jupyterhub deployment, and are optional.

### HTTPS Config

#### Setting up DNS for Lets Encrypt

Lets Encrypt is used to handle HTTPS certificates automatically. Jupyterhub can have unusual problems in HTTP mode only, so I would strongly strongly advice you run it with some level of TLS.

Simply ensure you have:
- An external IP address
- A internet routable domain name
- A (optionally/and/or) AAAA record(s) pointing to the IP address

Update the config file with the domain name.

#### Using existing TLS Certificate 

Alternatively, if you already have an existing certificate and don't want to expose the service externally you can manually provide a certificate.

The primary disadvantage of this, is both remembering to renew the certificate annually and the associated downtime compared to the automatic Lets Encrypt method.

A Kubernetes secret is used, instructions can be found [here](https://zero-to-jupyterhub.readthedocs.io/en/latest/administrator/security.html#specify-certificate-through-secret-resource)

### SSL Setup

The Lets Encrypt (LE) certificate will have failed to issue, as the LB takes longer to create than the first issue. To issue your first certificate and enable automatic renewal:

As there are a limited number of attempts we can do (see [rate limit](https://letsencrypt.org/docs/rate-limits/)) some sanity checks help ensure we don't run out of attempts:

- Check deployed `config.yaml` for the domain name
- Test that the domain is using the correct external IP **from an external server** with `dig`. E.g. `dig example.com @1.1.1.1`
- Test that the HTTP server is serving with `telnet example.com 80`

We need to force the HTTPS issuer to retry:
- `kubectl get pods -n jupyterhub` and take note of the pod name with `autohttps`
- Delete the auto HTTPS pod like so: `kubectl delete pod/autohttps-f954bb4d9-p2hnd` with the unique suffix varying on your cluster
- Wait 1 minute. The logs can be monitored with: `watch kubectl logs service/proxy-public -n jupyterhub -c traefik`
- Warnings about implicit names can be ignored. If successful there will be *no* error printed after a minute.
- Go to `https://<domain>.com` and it should be encrypted.

### Note on Renewal Limits

A maximum of 5 certificates will be issued to a set of domain names per week (on a 7 day rolling basis). Updating a deployment does not count towards this as Kubernetes holds the TLS secret. 

However, `helm uninstall jhub` will delete the certificate counting towards another when redeployed.

The currently issued certificate(s) can be viewed at: https://crt.sh/

## Maintenance and Notes

If your are maintaining the service there are a couple of important things to note:

### Single hub instance

Jupyterhub is not designed for high availability, this means only a single pod can ever exist. Any upgrades or modifications to the service will incur a user downtime of a few minutes.

Any existing Pods containing user work will not be shutdown or restarted unless the profiles have changed. To be clear, hub redeploying will have a minor outage but without clearing existing work.

### Autoscaler

The autoscaler is the most "brittle" part of the deployment as it has to work with heat. The logs can be monitored with:

- `kubectl logs deployment/cluster-autoscaler --follow -n kube-system`

The maximum number of nodes can be changed with:

- `kubectl edit deployment/cluster-autoscaler -n kube-system`
- Under image arguments the max number of instances can be changed
- Saving the file will redeploy the auto scaler with the new settings immediately.

### Proxy_public service notes

Deleting the public service endpoint does not delete the load balancer associated. **You must delete the load balancer** to prevent problems, as any redeployment of the service uses the existing LB without updating the members inside. This will cause the failover to stop working as well.

The following symptoms of this happening are:
- `kubectl get all -n kube-system` shows everything but the external service as completed
- The external service will be pending, but on the openstack GUI the LB will be active (not updating / creating)
- The service is not accessible as the old pod is still referred to.

To fix this:
- Delete the service in Kubernetes and load balancer in openstack
- Re-run the ansible deployment script (see deploy Jupyterhub), this will recreate the service.
- Associate the desired floating IP as described above

### Longhorn

Longhorn's configuration is defined by the `release_values` in `roles/deploy_hub/tasks/main.yml`. By default, this creates a load balancer for the UI labelled `longhorn-frontend`, which must be associated with a prepared FIP, as described for JupyterHub's `proxy_public` load balancer.

If you are required to uninstall and reinstall Longhorn, is may be necessary to manually delete the load balacer on OpenStack and the service (`kubectl get services -n longhorn-system` will list these). You must then restart the OpenStack controller manager pods before a new Longhorn load balancer can be created successfully.

