# Azure deployment

The implemented deployment target is a single Azure Linux VM running the same application and read-only MCP containers as the local profile. SQLite resides in a Docker named volume on the VM's managed OS disk. It survives application restarts, container recreation and VM stop/start. This is a single-user PoC, with no public web endpoint, application login, high availability or tenant authorization. The VM accepts SSH only from the specified operator address. Use SSH forwarding to reach the application.

Azure Container Apps plus PostgreSQL is an appropriate future managed deployment, but this repository does not implement a PostgreSQL storage adapter. Do not put the SQLite WAL ledger on Azure Files or scale the SQLite profile across replicas. Azure Container Apps container-local storage is ephemeral; a container image alone would not provide durable ledger storage ([Microsoft storage documentation](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts)).

## Provision

These commands create billable resources. They are supplied for the operator and have not been executed by the build agent. Select a subscription, resource group, region, VM size and your own public IP. `sshPublicKey` must contain a public key, never a private key.

```bash
az login
az account set --subscription YOUR_SUBSCRIPTION_ID
az group create --name chronoverse-poc --location southeastasia
az deployment group create \
  --resource-group chronoverse-poc \
  --template-file deploy/azure-vm.bicep \
  --parameters sshPublicKey="$(cat ~/.ssh/id_ed25519.pub)" operatorCidr=YOUR_PUBLIC_IP/32
```

The `host` output is the VM's IP address. Wait for bootstrap to finish:

```bash
ssh chrono@VM_IP 'sudo cloud-init status --wait'
```

## Transfer and start

From the project root, package only application code, lockfiles and deployment configuration. Research sources, local datasets, environment files, model caches and private keys are excluded.

```bash
tar -czf /tmp/chronoverse-app.tar.gz \
  --exclude='.venv' --exclude='__pycache__' --exclude='.pytest_cache' \
  --exclude='node_modules' --exclude='dist' \
  backend frontend Dockerfile compose.yaml
scp /tmp/chronoverse-app.tar.gz chrono@VM_IP:~/
ssh chrono@VM_IP 'mkdir -p ~/chronoverse && tar -xzf ~/chronoverse-app.tar.gz -C ~/chronoverse && cd ~/chronoverse && sudo docker compose up --build -d'
```

Containers use the no-download lexical vector baseline by default. Local semantic mode is available in the Python startup script. To use semantic mode in Azure, build/install the semantic extra, download the model into a persistent cache, mount it and configure `CHRONOVERSE_EMBEDDINGS=semantic` and `CHRONOVERSE_MODEL_CACHE`. This is an optional configuration; the supplied compose stack remains fully runnable without model weights.

## Open the product

```bash
ssh -N -L 8000:127.0.0.1:8000 -L 8001:127.0.0.1:8001 chrono@VM_IP
```

Keep the tunnel running. Open [the workbench](http://127.0.0.1:8000) locally. Connect an MCP client to `http://127.0.0.1:8001/mcp`. If local ports are already occupied, forward different local ports and adjust the URLs. The MCP SDK validates the request Host and Origin for its local endpoint.

## Persistence and operations

Keep one app and one MCP process per ledger. The volume is shared on the same machine. `docker compose down` preserves it; `docker compose down -v` deletes it. The Bicep template sets the OS disk's VM delete option to `Detach`, but deleting the resource group can still delete that disk. Back up before replacing infrastructure. Do not copy only the SQLite database file while WAL writes are active; use SQLite's online backup API.

Dataset profiles also persist in the same volume under `/data/profiles/`, including `catalog.sqlite3`, per-profile ledgers and prepared import previews. The command below backs up only the original demo ledger. A complete dataset backup must include those profile databases with their relative paths; pause profile creation/imports while taking that multi-database backup. Restoring only the demo ledger does not restore uploaded profiles.

```bash
sudo docker compose exec -T app python -c "import sqlite3; src=sqlite3.connect('/data/chronoverse.sqlite3'); dst=sqlite3.connect('/data/backup.sqlite3'); src.backup(dst); dst.close(); src.close()"
sudo docker compose logs --tail=100 app mcp
```

Export the resulting backup off the VM as part of your operational process. A backup left on the same disk is not disaster recovery. The deployment has no automatic backup retention policy.

## Validation boundary

Bicep compilation checks syntax and local resource type metadata; it does not prove SKU availability, quota, policy compliance, image availability, region support, cloud-init success, container build success or a deployed endpoint. A real deployment must pass health checks and the MCP smoke script before it is described as verified on Azure.

References: [Azure Linux disks](https://learn.microsoft.com/en-us/azure/virtual-machines/linux/tutorial-manage-disks), [Azure Container Apps storage](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts).
