FROM kartoza/geoserver:2.27.2

RUN wget https://jdbc.postgresql.org/download/postgresql-42.2.27.jar \
    -O /usr/local/tomcat/webapps/geoserver/WEB-INF/lib/postgresql.jar

RUN apt-get update && apt-get install -y --no-install-recommends jq \
    && rm -rf /var/lib/apt/lists/*


COPY init.sh /init.sh
# FIXME: floodstyle is not broadcasted and recognized by qgis.
COPY floodstyle.sld /floodstyle.sld
COPY entrypoint.sh /entrypoint.sh

RUN chmod  +x /entrypoint.sh /init.sh

ENTRYPOINT ["/entrypoint.sh"]
