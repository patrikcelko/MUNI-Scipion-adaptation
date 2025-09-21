# Scipion Kubernetes adaptation

TODO - This will be rewritten, now it is only used as cheat sheet

## Install microk8s stuf

``` shell
sudo snap install microk8s --classic
sudo usermod -aG microk8s $USER
sudo chown -f -R $USER ~/.kube
```

## Kill all

``` shell
sudo microk8s kubectl -n default scale deploy/scipion-scipion3-remote --replicas=0
sudo microk8s kubectl -n default delete pod imgtest --ignore-not-found
sudo microk8s kubectl -n default delete pod pvc-test --ignore-not-found
sudo microk8s kubectl -n default get rs -l app.kubernetes.io/instance=scipion -o wide
sudo microk8s kubectl -n default delete rs -l app.kubernetes.io/instance=scipion
```

## Run single node

``` shell
sudo microk8s kubectl -n default scale deploy/scipion-scipion3-remote --replicas=1
sudo microk8s kubectl -n default rollout status deploy/scipion-scipion3-remote
sudo microk8s kubectl -n default get deploy,rs,pods -l app.kubernetes.io/instance=scipion -o wide
```

## Version bump

``` shell
export VEERSION="0.4.5"

docker build  --network=host -t localhost:32000/scipion3-remote:v${VEERSION} ./docker
docker push localhost:32000/scipion3-remote:v${VEERSION}

sudo microk8s helm upgrade --install scipion ./helm/scipion3-remote/ -n default --set image.repository=localhost:32000/scipion3-remote --set image.tag=v${VEERSION}
sudo microk8s kubectl -n default logs -f deploy/scipion-scipion3-remote
sudo microk8s kubectl -n default delete pod -l app.kubernetes.io/name=scipion3-remote
sudo microk8s kubectl -n default rollout status deploy/scipion-scipion3-remote
```

## Base CMD

``` shell
sudo KUBECONFIG=/var/snap/microk8s/current/credentials/client.config kubectl
```

## Fixing cert

``` shell
sudo microk8s stop
sudo rm -f /var/snap/microk8s/common/var/lib/kubelet/pki/kubelet.crt /var/snap/microk8s/common/var/lib/kubelet/pki/kubelet.key
sudo microk8s start
sudo microk8s status --wait-ready
```
