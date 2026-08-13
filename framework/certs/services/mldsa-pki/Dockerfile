FROM alpine:3.23

RUN apk add --no-cache openssl

COPY provision.sh /usr/local/bin/provision-mldsa65-pki
RUN chmod 0755 /usr/local/bin/provision-mldsa65-pki

ENTRYPOINT ["/usr/local/bin/provision-mldsa65-pki"]
