#!/usr/bin/env bash
if [ -f /config/scripts/Sonarr_Kodi/.auto_config_complete ]; then
    echo "************ Skipping Sonarr Config************"
    sleep infinity
fi

echo "************ Configuring Sonarr Custom Scripts *************"

# Get Arr App information
if [ -z "$arrUrl" ] || [ -z "$arrApiKey" ]; then
arrUrlBase="$(cat /config/config.xml | xq | jq -r .Config.UrlBase)"
if [ "$arrUrlBase" == "null" ]; then
    arrUrlBase=""
else
    arrUrlBase="/$(echo "$arrUrlBase" | sed "s/\///g")"
fi
arrName="$(cat /config/config.xml | xq | jq -r .Config.InstanceName)"
arrApiKey="$(cat /config/config.xml | xq | jq -r .Config.ApiKey)"
arrPort="$(cat /config/config.xml | xq | jq -r .Config.Port)"
arrUrl="http://127.0.0.1:${arrPort}${arrUrlBase}"
fi

until false
do
arrApiTest=""
arrApiVersion=""
if [ "$arrPort" == "8989" ] || [ "$arrPort" == "7878" ]; then
    arrApiVersion="v3"
elif [ "$arrPort" == "8686" ] || [ "$arrPort" == "8787" ]; then
    arrApiVersion="v1"
fi
arrApiTest=$(curl -s "$arrUrl/api/$arrApiVersion/system/status?apikey=$arrApiKey" | jq -r .instanceName)
if [ "$arrApiTest" == "$arrName" ]; then
    break
else
    echo "$arrName is not ready, sleeping until valid response..."
    sleep 1
fi
done


if curl -s "$arrUrl/api/v3/notification" -H "X-Api-Key: ${arrApiKey}" | jq -r .[].name | grep "Sonarr_Kodi" | read; then
    echo "************ Sonarr_Kodi already configured ************"
    touch /config/scripts/Sonarr_Kodi/.auto_config_complete
else
    echo "Adding Sonarr_Kodi to custom scripts"
    # Send a command to check file path, to prevent error with adding...
    updateArr=$(curl -s "$arrUrl/api/v3/filesystem?path=%2Fconfig%2Fscripts%2FSonarr_Kodi%2Fsonarr_kodi.py&allowFoldersWithoutTrailingSlashes=true&includeFiles=true" -H "X-Api-Key: ${arrApiKey}")
    
    # Add sonarr_kodi.py
    updateArr=$(curl -s "$arrUrl/api/v3/notification?" -X POST -H "Content-Type: application/json" -H "X-Api-Key: ${arrApiKey}" --data-raw '{"onGrab": true,"onDownload": true,"onUpgrade": true,"onRename": true,"onSeriesAdd": true,"onSeriesDelete": true,"onEpisodeFileDelete": true,"onEpisodeFileDeleteForUpgrade": true,"onHealthIssue": true,"onHealthRestored": true,"onApplicationUpdate": true,"onManualInteractionRequired": true,"supportsOnGrab": true,"supportsOnDownload": true,"supportsOnUpgrade": true,"supportsOnRename": true,"supportsOnSeriesAdd": true,"supportsOnSeriesDelete": true,"supportsOnEpisodeFileDelete": true,"supportsOnEpisodeFileDeleteForUpgrade": true,"supportsOnHealthIssue": true,"supportsOnHealthRestored": true,"supportsOnApplicationUpdate": true,"supportsOnManualInteractionRequired": true,"includeHealthWarnings": true,"name": "Sonarr_Kodi","fields":[{"name":"path","value":"/config/scripts/Sonarr_Kodi/sonarr_kodi.py"},{"name":"arguments"}],"implementationName":"Custom Script","implementation":"CustomScript","configContract":"CustomScriptSettings","infoLink":"https://wiki.servarr.com/sonarr/supported#customscript","message":{"message":"Testing will execute the script with the EventType set to Test, ensure your script handles this correctly","type":"warning"},"tags":[]}')

    error=$(jq -r .[0].errorMessage <<< "$updateArr")

    if [ -z "$error" ]; then
        echo "Script Configured Sucessfully"
        touch /config/scripts/Sonarr_Kodi/.auto_config_complete
        exit 0
    fi

    # Parse Failure
    if [ "$error" == "File does not exist" ]; then
        echo "Script not found, check that git has cloned the repo"
    elif [[ "$error" == *"Permission denied"* ]]; then
        echo "Script has incorrect permissions"
    elif [ ! -z "$error" ]; then
        echo "Script Test Failed"
    else
        echo "Unknown Error While configuring script"
    fi
    echo "Error: $error"
    echo "Sonarr_Kodi was not configured properly"

fi

exit