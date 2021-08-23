import json
import datetime
import os
import re
import sys
import pymysql
from datetime import datetime

TABLE_NAME = "canary_issues"
c = None
conn = None

def env_set(env_var, default):
    if env_var in os.environ:
        return os.environ[env_var]
    elif os.path.exists(env_var) and os.path.getsize(env_var) > 0:
        with open(env_var, 'r') as env_file:
            var = env_file.read().strip()
            env_file.close()
        return var
    else:
        return default

def connect_to_db():
    db_user = env_set('db_user', 'root')
    db_host = env_set('db_host', 'localhost')
    db_pass = env_set('db_pass', None)
    db_port = env_set('db_port', 3306)
    global conn, c
    conn = pymysql.connect(host=db_host,user=db_user,db="tests",password=db_pass,port=int(db_port))
    c = conn.cursor()
    sql = "CREATE TABLE IF NOT EXISTS {} (\
        id int NOT NULL AUTO_INCREMENT, \
        github_id text, \
        status text, \
        first_snapshot text, \
        last_snapshot text, \
        z_release text, \
        hub_version text, \
        hub_platform text, \
        import_cluster_details text, \
        severity text, \
        priority text, \
        first_date datetime, \
        last_date datetime, \
        days_duped float, \
        squad_tag text, \
        payload text, \
        dup_count int, \
        PRIMARY KEY (id))".format(TABLE_NAME)
    c.execute(sql)

def payload_exists(payload_string, snapshot):
    global conn, c, TABLE_NAME
    payload = sanitize_payload(payload_string)
    dup = None

    sql = "SELECT id, github_id, first_date, last_date, first_snapshot, last_snapshot, dup_count FROM {} WHERE payload = \"{}\" AND status = \"open\";".format(TABLE_NAME,payload)
    num_rows = c.execute(sql)
    fetch = c.fetchone()
    if (num_rows > 0):
        # We have a match based on payload
        real_id = list(fetch)[0]
        dup = list(fetch)[1]
        github_id = dup
        first_date = list(fetch)[2]
        last_date = list(fetch)[3]
        first_snapshot = list(fetch)[4]
        last_snapshot = list(fetch)[5]
        dup_count = list(fetch)[6] + 1 # Since we need to bump it if we make any updates
        this_date = snapshot_to_date(snapshot)
        if last_date == "0000-00-00 00:00:00":
            # We have an existing snapshot, and this is the first dup - figure out where to insert it time-wise
            if this_date < first_date:
                # The incoming snapshot predates the existing snapshot
                distance = first_date - this_date
                days = distance.total_seconds() / 60 / 60 / 24
                sql = "UPDATE {} SET first_date = \"{}\", last_date = \"{}\", days_duped = \"{}\", first_snapshot = \"{}\", last_snapshot = \"{}\", dup_count = \"{}\" WHERE id = \"{}\";".format(TABLE_NAME, this_date, first_date, days, snapshot, first_snapshot, dup_count, real_id)
            elif this_date > first_date:
                # The incoming snapshot is later than the existing snapshot
                distance = this_date - first_date
                days = distance.total_seconds() / 60 / 60 / 24
                sql = "UPDATE {} SET last_date = \"{}\", days_duped = \"{}\", last_snapshot = \"{}\", dup_count = \"{}\" WHERE id = \"{}\";".format(TABLE_NAME, this_date, days, snapshot, dup_count, real_id)
            else:
                # The incoming snapshot is the same, so we'll ignore it
                sql = ""
        else:
            # We have an existing snapshot - figure out if we need to insert it time-wise or just dup it
            if this_date < first_date:
                # The incoming snapshot predates the first snapshot to see this payload
                distance = last_date - this_date
                days = distance.total_seconds() / 60 / 60 / 24
                sql = "UPDATE {} SET first_date = \"{}\", days_duped = \"{}\", first_snapshot = \"{}\", dup_count = \"{}\" WHERE id = \"{}\";".format(TABLE_NAME, this_date, days, snapshot, dup_count, real_id)
            elif this_date > last_date:
                # The incoming snapshot is later than the existing snapshot
                distance = this_date - first_date
                days = distance.total_seconds() / 60 / 60 / 24
                sql = "UPDATE {} SET last_date = \"{}\", days_duped = \"{}\", last_snapshot = \"{}\", dup_count = \"{}\" WHERE id = \"{}\";".format(TABLE_NAME, this_date, days, snapshot, dup_count, real_id)
            elif (this_date == first_date) or (this_date == last_date):
                # The incoming date is one we've seen before, so we'll ignore it
                sql = ""
            else:
                # This is a dup somewhere in the middle
                sql = "UPDATE {} SET dup_count = \"{}\" WHERE id = \"{}\";".format(TABLE_NAME, dup_count, real_id)
        if sql != "":
            return_code = c.execute(sql)
            conn.commit()

    return dup

def update_status(real_id, status):
    global conn, c, TABLE_NAME
    sql = "UPDATE {} SET status = \"{}\" WHERE id = \"{}\";".format(TABLE_NAME, status, real_id)
    return_code = c.execute(sql)
    conn.commit()
    print("SQL: {} Update db id {} to status {}: {}".format(sql, real_id,status,return_code))
    return return_code

def insert_canary_issue(issue):
    global conn, c, TABLE_NAME
    import_details_string = issue['import_cluster_details']
    import_details = "{}".format(import_details_string)
    import_details = import_details.replace('"', '""')
    payload = sanitize_payload(issue['payload'])
    first_snapshot = issue['first_snapshot']
    iso_date = snapshot_to_date(first_snapshot)
    datestuff = first_snapshot.split('-')
    sql = "INSERT into {} values ({}, {}, {}, {}, {}, \"{}\", {}, {}, \"{}\", {}, {}, \"{}\", \"{}\", \"{}\", {}, \"{}\", {})".format(TABLE_NAME, \
        0, \
        json.dumps(issue['github_id']), \
        json.dumps(issue['status']), \
        json.dumps(issue['first_snapshot']), \
        "null", \
        datestuff[0], \
        json.dumps(issue['hub_version']), \
        json.dumps(issue['hub_platform']), \
        import_details, \
        json.dumps(issue['severity']), \
        json.dumps(issue['priority']), \
        iso_date, \
        "null", \
        0.0, \
        json.dumps(issue['squad_tag']), \
        payload, \
        0 )
    return_code = c.execute(sql)
    conn.commit()
    return return_code

def sanitize_payload(incoming):
    _payload = "{}".format(incoming)
    _payload = _payload.replace('"', '""')
    # Rip out any big number (typically seen as job numbers)
    _payload = re.sub(r'\d{5,10}', '<VAR_NUM>', _payload)
    # Rip out any defect identifiers
    _payload = re.sub(r'defect #\d{1,10}', 'defect #<VAR_NUM>', _payload)
    return _payload

def snapshot_to_date(snapshot):
    datestuff = snapshot.split('-')
    iso_date = "{}-{}-{} {}:{}:{}".format(datestuff[2],datestuff[3],datestuff[4],datestuff[5],datestuff[6],datestuff[7])
    datetime_object = datetime.strptime(iso_date, '%Y-%m-%d %H:%M:%S')
    return datetime_object

def pull_open_defects():
    sql = "SELECT id, github_id FROM {}  WHERE status != \"closed\";".format(TABLE_NAME)
    num_rows = c.execute(sql)
    if (num_rows > 0):
        return c.fetchall()
    else:
        return None
 
def disconnect_from_db():
    conn.commit()
    conn.close()
