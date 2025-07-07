FROM kartoza/geoserver:2.26.0

RUN wget https://jdbc.postgresql.org/download/postgresql-42.2.27.jar \
    -O /usr/local/tomcat/webapps/geoserver/WEB-INF/lib/postgresql.jar
COPY 01_init_geoserver.sh /init.sh
COPY floodstyle.sld /floodstyle.sld
COPY entrypoint.sh /entrypoint.sh

RUN chmod   +x /entrypoint.sh /init.sh

ENTRYPOINT ["/entrypoint.sh"]


