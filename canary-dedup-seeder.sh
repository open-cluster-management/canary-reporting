#!/bin/sh

# Given a directory to start, seeds database with all canary results

process_canary () {
# -sn SNAPSHOT
# -hv HUB_VERSION
# -hp HUB_PLATFORM
# -ic IMPORT_CLUSTER_DETAILS_FILE
    BASE_PATH=$1
    echo BASE_PATH: $1
    RESULTS_JSON=$BASE_PATH/results.json
    if [ -f "$RESULTS_JSON" ]; then
        SNAPSHOT=$(jq -r '.snapshot' $RESULTS_JSON)
        HUB_VERSION=$(jq -r '.hub_version' $RESULTS_JSON)
        HUB_PLATFORM=$(jq -r '.hub_platform' $RESULTS_JSON)
        CLUSTER_DETAILS=$(jq -r '.import_cluster_details' $RESULTS_JSON)
        YEAR=$(echo $SNAPSHOT | awk -F"-" -s {'print $3'})
        MONTH=$(echo $SNAPSHOT | awk -F"-" -s {'print $4'})
        DAY=$(echo $SNAPSHOT | awk -F"-" -s {'print $5'})
        HOUR=$(echo $SNAPSHOT | awk -F"-" -s {'print $6'})
        MINUTE=$(echo $SNAPSHOT | awk -F"-" -s {'print $7'})
        SECOND=$(echo $SNAPSHOT | awk -F"-" -s {'print $8'})
        echo $CLUSTER_DETAILS > .icd.json
        python3 reporter.py gh --dry-run $BASE_PATH -sn $SNAPSHOT -hv $HUB_VERSION -hp $HUB_PLATFORM -ic .icd.json
        rm .icd.json
    else
        SNAPSHOT=`basename $BASE_PATH`
        python3 reporter.py gh --dry-run $BASE_PATH -sn $SNAPSHOT -hv UNKNOWN -hp UNKNOWN 
    fi
}

for f in $1/*; do
    if [ -d "$f" ]; then
        # Will not run if no directories are available
        process_canary "$f"
    fi
done
if [ -d "$1" ]; then
    process_canary "$1"
fi
