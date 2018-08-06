FROM python:3
USER root
ARG dockerGid=999
ADD libltdl.so.7 /usr/lib/x86_64-linux-gnu/
ADD gpu.py /gpu.py
RUN echo "docker:x:${dockerGid}:jenkins" >> /etc/group
RUN pip install requests
ENTRYPOINT python3 /gpu.py
