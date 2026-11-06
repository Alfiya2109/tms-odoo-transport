FROM odoo:18.0

USER root

# Install extra dependencies
RUN apt-get update && apt-get install -y \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy custom addons into Odoo addons path
COPY ./custom_addons /mnt/extra-addons

# Copy Odoo config
COPY ./deploy/odoo.conf /etc/odoo/odoo.conf

USER odoo

EXPOSE 8069

CMD ["odoo", "--config=/etc/odoo/odoo.conf"]
