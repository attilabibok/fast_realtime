
FROM kartoza/mapproxy
RUN pip install croniter
COPY reseed_cron.sh /reseed_cron.sh
RUN chmod +x /reseed_cron.sh
CMD ["/reseed_cron.sh"]