FROM postgres:14
COPY ops/init-postgres.sh /docker-entrypoint-initdb.d/10-tracker-roles.sh
RUN sed -i 's/\r$//' /docker-entrypoint-initdb.d/10-tracker-roles.sh
