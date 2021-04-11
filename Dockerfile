FROM python:3.7-slim-buster

RUN apt-get update
RUN apt-get -y install jq

COPY entrypoint.sh /action/entrypoint.sh
COPY run_action.py /action/run_action.py
COPY requirements.txt /action/requirements.txt

RUN pip3 install -r /action/requirements.txt
RUN pip3 install requests

ENTRYPOINT ["/action/entrypoint.sh"]
