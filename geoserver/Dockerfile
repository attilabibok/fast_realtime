FROM kartoza/geoserver:2.27.2

RUN wget https://jdbc.postgresql.org/download/postgresql-42.2.27.jar \
    -O /usr/local/tomcat/webapps/geoserver/WEB-INF/lib/postgresql.jar
# TODO: replace 01_init_geoserver.sh with a zipped and ready geoserver_data folder
COPY init.sh /init.sh
# FIXME: floodstyle is not broadcasted and recognized by qgis.
COPY floodstyle.sld /floodstyle.sld
COPY entrypoint.sh /entrypoint.sh

RUN chmod  +x /entrypoint.sh /init.sh

ENTRYPOINT ["/entrypoint.sh"]
