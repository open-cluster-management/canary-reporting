import os, sys, json, db_utils
import pymysql
from github import Github, UnknownObjectException
from datetime import datetime

# Aligns all defects recorded in database with their github status

TABLE_NAME = "canary_issues"
c = None
conn = None
github_token=os.getenv('GITHUB_TOKEN')
github_org=os.getenv('GITHUB_ORG')
github_repo=os.getenv('GITHUB_REPO')

def query_github_status(defect):
    try:
        issue_state = repo.get_issue(defect).state
    except UnknownObjectException:
        issue_state = None
    return issue_state

#
# Get conneted to the Database
#
ret = db_utils.connect_to_db()

#
# Get connected to GitHub
#
github_token=os.getenv('GITHUB_TOKEN')
try:
    g = Github(github_token)
    org = g.get_organization(github_org)
    repo = org.get_repo(github_repo)
except UnknownObjectException as ex:
    print(ex)
    exit(1)

ret = db_utils.pull_open_defects()
if ret != None:
    open_defects = list(ret)
    for row in open_defects:
        id = list(row)[0]
        defect = list(row)[1]
        status = query_github_status(int(defect))
        if (status != "open") and (status != None):
            db_utils.update_status(id,status)
else:
    print("No open defects!")
ret = db_utils.disconnect_from_db()
