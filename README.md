### monitor the gpu of k8s clkuster

This project could monitor the used of gpu in k8s cluster on node level and pod level;

1、prepare

* k8s cluster
* nvidia-docker2
* k8s-nvidia-plugin
* influxdb database

2、edit the file [gpu.py](https://github.com/694982827/k8s-gpu-monitor/blob/master/gpu.p

replace the` posturl` with your influxdb file.

3、build  your img

```shell
docker build -t YOURIMG:TAG .
```



 