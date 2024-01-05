#!/usr/bin/with-contenv bash
echo "************ Install Packages ************"
apk add -U --update --no-cache \
	git \
	python3 \
	py3-pip

echo "************ install python packages ************"
pip install --upgrade --no-cache-dir -U --break-system-packages \
	yq


echo "************ Setup Script Directory ************"
if [ ! -d /config/scripts ]; then
	mkdir -p /config/scripts
fi

echo "************ Download / Update Repo ************"
if [ -d /config/scripts/Sonarr_Kodi ]; then
    git -C /config/scripts/Sonarr_Kodi pull
else
    git clone https://github.com/jsaddiction/Sonarr_Kodi.git /config/scripts/Sonarr_Kodi
fi

echo "************ Install Script Dependencies ************"
pip install --upgrade pip --no-cache-dir --break-system-packages
pip install -r /config/scripts/Sonarr_Kodi/requirements.txt --no-cache-dir --break-system-packages

echo "************ Set Permissions ************"
chmod 777 -R /config/scripts/Sonarr_Kodi

echo "************ Configuring Sonarr *********"
if [ ! -d /custom-services.d ]; then
    mkdir -p /custom-services.d
fi

if [ -f /custom-services.d/config_sonarr.sh ]; then
	rm -rf /custom-services.d/config_sonarr.service
fi

cp /config/scripts/Sonarr_Kodi/installer/config_sonarr.sh /custom-services.d/config_sonarr.service

exit