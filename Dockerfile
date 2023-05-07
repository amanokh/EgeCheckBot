FROM python:3.11.3

WORKDIR /bot
ADD requirements.txt /bot

RUN pip3 install -r requirements.txt

ADD . /bot

ENTRYPOINT ["python3", "main.py"]