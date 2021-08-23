"""GitHubIssueGenerator

An AbstractGenerator and ReportGenerator implementation to generate a markdown report as part of the canary reporting CLI.  
This class can generate its CLI parser, load args, generate a ResultsAggregator object, and format the output data as a md report. 
"""

import os, sys, json, argparse, itertools, db_utils
from github import Github, UnknownObjectException
from generators import AbstractGenerator,ReportGenerator
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from datamodel import ResultsAggregator as ra
from random import randrange
from datetime import datetime

class GitHubIssueGenerator(AbstractGenerator.AbstractGenerator, ReportGenerator.ReportGenerator):

    header_symbols = {
        f"{ra.ResultsAggregator.failed}": ":red_circle:",
        f"{ra.ResultsAggregator.passed}": ":white_check_mark:",
        f"{ra.ResultsAggregator.skipped}": ":large_blue_circle:",
        f"{ra.ResultsAggregator.ignored}": ":warning:"
    }

    status_symbols = {
        f"{ra.ResultsAggregator.failed}": ":x:",
        f"{ra.ResultsAggregator.passed}": ":white_check_mark:",
        f"{ra.ResultsAggregator.skipped}": ":large_blue_circle:",
        f"{ra.ResultsAggregator.ignored}": ":large_orange_diamond:"
    }

    quality_symbols = {
        f"{ra.ResultsAggregator.failed}": ":red_circle:",
        f"{ra.ResultsAggregator.passed}": ":white_check_mark:",
        f"{ra.ResultsAggregator.ignored}": ":warning:",
    }

    # Dict containing tag shortname (used in metadata) to actual tag value (in GitHub)
    tag_mappings = {
        "sev1": "Severity 1 - Urgent",
        "sev2": "Severity 2 - Major",
        "sev3": "Severity 3 - Minor",
        "p0": "blocker (P0)",
        "p1": "Priority/P1",
        "p2": "Priority/P2",
        "p3": "Priority/P3"
    }

    severities = [
        "Severity 1 - Urgent",
        "Severity 2 - Major",
        "Severity 3 - Minor"
    ]

    priorities = [
        "blocker (P0)",
        "Priority/P1",
        "Priority/P2",
        "Priority/P3"
    ]

    def __init__(self, results_dirs, snapshot=None, branch=None, stage=None, hub_version=None, 
        hub_platform=None, import_cluster_details=[], job_url=None, build_id=None,
        sd_url=None, md_url=None, must_gather_url=None, results_url=None, ignorelist=[], assigneelist={},
        passing_quality_gate=100, executed_quality_gate=100, github_token=os.getenv('GITHUB_TOKEN'), github_org=["open-cluster-management"],
        github_repo=["cicd-staging"], tags=[], dry_run=True, output_file="github.md",
        consolidated_defect=True, persquad_defect=False):
        """Create a GitHubIssueGenerator Object, unroll xml files from input, and initialize a ResultsAggregator.  

        Required Arguments:
        results_dirs    -- a list of directories that contain XML files from which to generate an aggregate report

        Keyword Arguments:
        snapshot    --  a string representation of the snapshot that these test results represent, ex. 2.2.0-SNAPSHOT-timestamp
        branch      --  a string representaiton of the integration test branch that generated the xml results, ex. 2.2-integration
        stage       --  a string representaiton of the integration test stage/step that generated the xml results, ex deploy
        hub_version     --  a string representation of the hub cluster version that was tested
        hub_platform    --  a string representation of the hub cluster's hosting cloud platform
        import_cluster_details  --  a list of dicts, each identifying an import cluster's clustername, version, and platform
        job_url     --  the URL of the CI job that produced this JUnit XML, ex. $TRAVIS_BUILD_WEB_URL
        build_id    --  CI build id (unique identifier) that produced this JUnit XML, ex. $TRAVIS_BUILD_ID
        sd_url      --  the URL of any snapshot diff report generated previously for this snapshot
        md_url      --  the URL of any hosted md report generated previously from this XML
        must_gather_url     --  the URL of an s3 bucket containing must-gather data from this test
        results_url         --  the URL of an s3 bucket containing the raw XML results from this test
        ignorelist          --  a list of dicts contianing "name", "squad", and "owner" keys
        assigneelist        --  a dict containing assignees for issue creation per squad
        passing_quality_gate    --  a number between 0 and 100 that defines the percentage of tests that must pass to declare success
        executed_quality_gate   --  a number between 0 and 100 that defines the percentage of tests that must be executed to declare success
        github_token    --  the user's github token used to access/create the GitHub issue - loaded from the GITHUB_TOKEN env var if not set
        github_org      --  the github organization where the git issue should be created
        github_repo     --  the github repo where the git issue should be created
        tags    --  a list of github tags that should be applied to the git issue
        dry_run --  toggles actual github creation - if present issues will not actually be created, but we'll run through the paces
        output_file --  a place to output the git issue's raw markdown, especially useful when using dry-run
        consolidated_defect --  original, consolidated defect creation in github when dry_run is not on
        persquad_defect --  create issues only if a unique set of failures appears by squad (and dry_run is not on) - requires database connection
        """
        self.snapshot = snapshot
        self.branch = branch
        self.stage = stage
        self.hub_version = hub_version
        self.hub_platform = hub_platform
        self.import_cluster_details = import_cluster_details
        self.job_url = job_url
        self.build_id = build_id
        self.sd_url = sd_url
        self.md_url = md_url
        self.mg_url = must_gather_url
        self.results_url = results_url
        self.ignorelist = ignorelist
        self.assigneelist = assigneelist
        self.passing_quality_gate = passing_quality_gate
        self.executed_quality_gate = executed_quality_gate
        self.results_files = []
        self.github_token = github_token
        self.github_org = github_org
        self.github_repo = github_repo
        self.tags = tags
        self.dry_run = dry_run
        self.output_file = output_file
        self.consolidated_defect = consolidated_defect
        self.persquad_defect = persquad_defect
        for _results_dir in results_dirs:
            _files_list = os.listdir(_results_dir)
            for _f in _files_list:
                _full_path = os.path.join(_results_dir, _f)
                if os.path.isfile(_full_path) and _full_path.endswith('.xml'):
                    self.results_files.append(_full_path)
        self.aggregated_results = ra.ResultsAggregator(files=self.results_files, ignorelist=ignorelist)

    def generate_subparser(subparser):
        """Static method to generate a subparser for the GitHubIssueGenerator module.  

        Required Argument:
        subparser -- an argparse.ArgumentParser object to extend with a new subparser.  
        """
        subparser_name = 'gh'
        gh_parser = subparser.add_parser(subparser_name, parents=[ReportGenerator.ReportGenerator.generate_parent_parser()],
            help="Generate a GitHub issue on a given GitHub repo with artifacts from input JUnit XML tests if a failure is detected.",
            formatter_class=argparse.RawTextHelpFormatter,
            epilog="""
Example Usages:

    Generate a GitHub issue-style md report from the JUnit xml in the 'juint_xml' folder and save it locally to 'github.md':
        python3 reporter.py gh junit_xml/ -o github.md --dry-run

    Generate a GitHub issue-style md report from the JUnit xml in the 'juint_xml' folder and save it locally to 'github.md' with ignorelist.json as an ignorelist:
        python3 reporter.py gh junit_xml/ -o github.md --dry-run --ignore-list=ignorelist.json

    Generate a GitHub issue-style md report from the JUnit xml in the 'juint_xml' folder and open a git issue in the org test_org in repo test_repo
        python3 reporter.py gh junit_xml/ --github-organization=test_org --repo=test_repo

    Generate a GitHub issue-style md report from the JUnit xml in the 'juint_xml' folder and open a git issue in the org test_org in repo test_repo with CLI-provided GITHUB_TOKEN
        python3 reporter.py gh junit_xml/ --github-organization=test_org --repo=test_repo --github-token=<YOUR_GITHUB_TOKEN>

    Generate the above report with some tags:
        python3 reporter.py gh junit_xml/ --github-organization=test_org --repo=test_repo --github-token=<YOUR_GITHUB_TOKEN> -t "blocker (P0)" -t "canary-failure" -t "Severity 1 - Urgent" -t "bug"
""")
        gh_parser.add_argument('--github-organization', nargs=1, default=["open-cluster-management"],
            help="GitHub organization to open an issue against if a failing test is detected.  Defaults to open-cluster-management.")
        gh_parser.add_argument('-r', '--repo', nargs=1, default=["backlog"],
            help="GitHub repo to open an issue against if a failing test is detected.  Defaults to 'backlog'.")
        gh_parser.add_argument('--github-token', default=os.getenv('GITHUB_TOKEN'),
            help="GitHub token for access to create GitHub issues.  Pulls from teh GITHUB_TOKEN environment variable if not specified.")
        gh_parser.add_argument('-md', '--markdown-url',
            help="URL of the markdown report file artifact associated with this report.")
        gh_parser.add_argument('-sd', '--snapshot-diff-url',
            help="URL of the snapshot diff file artifact associated with this report.")
        gh_parser.add_argument('-ru', '--results-url',
            help="URL of the S3 bucket containing full results artifacts.")
        gh_parser.add_argument('-mg', '--must-gather-url',
            help="URL of the S3 bucket containing must-gather artifacts.")
        gh_parser.add_argument('-o', '--output-file',
            help="If provided - GitHub issue contents will be mirrored to the input filename.")
        gh_parser.add_argument('-dr', '--dry-run', action='store_true',
            help="If provided - actual GitHub issue(s) will not be created, but the file will be generated, best used with -o.")
        consolidated_defect_parser = gh_parser.add_mutually_exclusive_group(required=False)
        consolidated_defect_parser.add_argument('-cd', '--consolidated-defect', dest='consolidated_defect', action='store_true',
            help="If provided - create the original, consolidated defect (assuming --dry-run is not set). Defaults to set.")
        consolidated_defect_parser.add_argument('-nocd', '--no-consolidated-defect', dest='consolidated_defect', action='store_false',
            help="If provided - do not create the original, consolidated defect.")
        gh_parser.set_defaults(consolidated_defect_parser=True)
        persquad_parser = gh_parser.add_mutually_exclusive_group(required=False)
        persquad_parser.add_argument('-psd', '--per-squad-defect', dest='persquad_defect', action='store_true',
            help="If provided - create defects on a per-squad basis (assuming --dry-run is not set). Defaults to not set.")
        persquad_parser.add_argument('-nopsd', '--no-per-squad-defect', dest='persquad_defect', action='store_false',
            help="If provided - do not create defects on a per-squad basis. Defaults to set.")
        gh_parser.set_defaults(persquad_parser=False)

        gh_parser.add_argument('-t', '--tags', action='append', default=[],
            help="GitHub issue tags to apply to the created issue.  Only applied if the tags exist on the target repository.")
        gh_parser.add_argument('-al', '--assignee-list',
            help="GitHub issue assignee for the created issue(s).  Only applied if the assignees exist on the target repository.")
        gh_parser.set_defaults(func=GitHubIssueGenerator.generate_github_issue_from_args)
        return subparser_name, gh_parser

    
    def generate_github_issue_from_args(args):
        """Static method to create a GitHubIssueGenerator object and generate a slack report from the command-line args.

        Required Argument:
        args -- argparse-generated arguments from an argparse with a parser generated by GitHubIssueGenerator.generate_subparser()
        """
        _ignorelist = []
        if args.ignore_list is not None and os.path.isfile(args.ignore_list):
            try:
                with open(args.ignore_list, "r+") as f:
                    _il = json.loads(f.read())
                _ignorelist = _il['ignored_tests']
            except json.JSONDecodeError as ex:
                print(f"Ignorelist found in {args.ignore_list} was not in JSON format, ignoring the ignorelist. Ironic.", file=sys.stderr, flush=False)
        _assigneelist = {}
        if args.assignee_list is not None and os.path.isfile(args.assignee_list):
            try:
                with open(args.assignee_list, "r+") as f:
                    _assigneelist = json.loads(f.read())
            except json.JSONDecodeError as ex:
                print(f"AssigneeList found in {args.assignee_list} was not in JSON format, ignoring the assigneelist.", file=sys.stderr, flush=False)
        _import_cluster_details = []
        if args.import_cluster_details_file is not None and os.path.isfile(args.import_cluster_details_file):
            try:
                with open(args.import_cluster_details_file, "r+") as f:
                    _import_cluster_details = json.loads(f.read())
            except json.JSONDecodeError as ex:
                print(f"Import cluster details found in {args.import_cluster_details_file} was not in JSON format, ignoring.", file=sys.stderr, flush=False)
        elif args.import_version or args.import_platform:
            _import_cluster = {
                "clustername": ""
            }
            _import_cluster["version"] = args.import_version if args.import_version else ""
            _import_cluster["platform"] = args.import_platform if args.import_platform else ""
            _import_cluster_details.append(_import_cluster)
        _generator = GitHubIssueGenerator(args.results_directory, snapshot=args.snapshot, branch=args.branch, stage=args.stage,
            hub_version=args.hub_version, hub_platform=args.hub_platform,
            import_cluster_details=_import_cluster_details, job_url=args.job_url, build_id=args.build_id, ignorelist=_ignorelist, assigneelist=_assigneelist,
            sd_url=args.snapshot_diff_url, md_url=args.markdown_url, executed_quality_gate=int(args.executed_quality_gate), passing_quality_gate=int(args.passing_quality_gate),
            results_url=args.results_url, must_gather_url=args.must_gather_url, github_token=args.github_token, github_org=args.github_organization,
            github_repo=args.repo, tags=args.tags, dry_run=args.dry_run, output_file=args.output_file,
            consolidated_defect=args.consolidated_defect, persquad_defect=args.persquad_defect)
        _message = _generator.open_github_issue()
        _generator.open_github_issues()

    
    def open_github_issues(self):
        # Connect to our duplicate detection database
        db_utils.connect_to_db()

        # Get all results of this canary test
        _results = self.aggregated_results.get_results()
        # Get just the failed tests
        _failures = list(filter(lambda a: a['state'] == "failed", _results))
        # Get a view of just the metadata to extract the list of squads
        _metadata = []
        for f in _failures:
            _metadata.append(f['metadata'])
        # What are the unique squads in that metadata?
        _squads = list(set(itertools.chain(*map(lambda r: r.get('squad(s)', "Unlabelled"), _metadata))))
        # Iterate over all squads and open an issue for that squad if one doesn't already exist for this set of failures
        for squad in _squads:
            _squad_issue_set = list(filter(lambda a: a['metadata']['squad(s)'][0] == squad, _failures))
            # Need to flatten issue set down to name, testsuite, squad, pri, sev
            _flat_issue_set = []
            _highest_sev=len(GitHubIssueGenerator.tag_mappings)
            _highest_pri=len(GitHubIssueGenerator.tag_mappings)
            for issue in _squad_issue_set:
                new_issue = {"name":issue['name'],"testsuite":issue['testsuite']}
                sev = GitHubIssueGenerator.tag_mappings.get(issue['metadata']['severity'].lower(), None)
                pri = GitHubIssueGenerator.tag_mappings.get(issue['metadata']['priority'].lower(), None)
                _highest_sev = GitHubIssueGenerator.severities.index(sev) if sev in GitHubIssueGenerator.severities and GitHubIssueGenerator.severities.index(sev) < _highest_sev else _highest_sev
                _highest_pri = GitHubIssueGenerator.priorities.index(pri) if pri in GitHubIssueGenerator.priorities and GitHubIssueGenerator.priorities.index(pri) < _highest_pri else _highest_pri
                _flat_issue_set.append(new_issue)
            if _highest_sev == len(GitHubIssueGenerator.tag_mappings):
                # A severity wasn't found, for some reason - assign highest
                _highest_sev = 0
            if _highest_pri == len(GitHubIssueGenerator.tag_mappings):
                # A priority wasn't found, for some reason - assign highest
                _highest_pri = 1 # 0 would be blocker, that's a little aggressive
            if len(_flat_issue_set) > 0:
                # Iterate through db, see if issue exists already
                _sh = "Unknown" if self.snapshot == None else self.snapshot
                dup = db_utils.payload_exists(_flat_issue_set, _sh)
                if dup == None:
                    # Get a local copy of tags they want us to add
                    _tags = self.tags.copy()
                    _tags.append(GitHubIssueGenerator.severities[_highest_sev])
                    _tags.append(GitHubIssueGenerator.priorities[_highest_pri])
                    _tags.append("squad:{}".format(squad))
                    github_id = self.open_github_issue_per_squad(_tags, squad)
                    if github_id == None:
                        github_id = "seed{}".format(randrange(100000,999999))
                    print(f"Unique issue, adding github id {github_id} severity '{GitHubIssueGenerator.severities[_highest_sev]}' and priority '{GitHubIssueGenerator.priorities[_highest_pri]}' for squad:{squad}.", file=sys.stderr, flush=False)
                    # Needed because "Object of type datetime is not JSON serializable"
                    _now = "{}".format(datetime.utcnow())
                    _hv = "Unknown" if self.hub_version == None else self.hub_version
                    _hp = "Unknown" if self.hub_platform == None else self.hub_platform
                    entry = {"github_id":github_id, "first_snapshot":_sh, "hub_version":_hv, "hub_platform":_hp, "import_cluster_details":self.import_cluster_details, "status":"open","severity":GitHubIssueGenerator.severities[_highest_sev],"priority":GitHubIssueGenerator.priorities[_highest_pri],"date":_now,"squad_tag":"squad:{}".format(squad),"payload":_flat_issue_set}
                    print(f"Return code from database insert: {db_utils.insert_canary_issue(entry)}", file=sys.stderr, flush=False)
                else:
                    print(f"squad:{squad} is a duplicate of issue {dup}.", file=sys.stderr, flush=False)
        db_utils.disconnect_from_db()

    def open_github_issue_per_squad(self, _tags, squad):
        """Macro function to assemble and open GitHub Issues, one per squad.  This wraps the title, body, and tag assembly and issue generation."""
        _message = self.generate_github_issue_body()
        _github_tags_objects = []
        _assignees=[]
        if self.persquad_defect and not self.dry_run:
            try:
                g = Github(self.github_token)
                org = g.get_organization(self.github_org[0])
                repo = org.get_repo(self.github_repo[0])
            except UnknownObjectException as ex:
                print(f"Failed login to GitHub or find org/repo.  See error below for additional details: {ex}", file=sys.stderr, flush=False)
                exit(1)
            print(f"Using github org {self.github_org[0]}, repo {self.github_repo[0]}", file=sys.stderr, flush=False)
            for tag in _tags:
                try:
                    _github_tags_objects.append(repo.get_label(tag))
                except UnknownObjectException as ex:
                    print(f"Couldn't find GitHub Tag {tag}, skipping and continuing.", file=sys.stderr, flush=False)
                    pass
            for tag in _tags:
                try:
                    if "squad:{}".format(tag) in self.assigneelist:
                        _assignees.append(GitHubIssueGenerator.get_user(org, self.assigneelist[tag]))
                except UnknownObjectException as ex:
                    print(f"No user for {tag}, skipping and continuing.", file=sys.stderr, flush=False)
                    pass
            _issue_title = "{}:{}".format(self.generate_issue_title(),squad)
            _issue = repo.create_issue(_issue_title, body=_message, labels=_github_tags_objects, assignees=_assignees)
            print(_issue.html_url)
            return _issue.number
        else:
            print(f"--dry-run or --no-per-squad-defect has been set, skipping squad's git issue creation", file=sys.stderr, flush=False)
            print(f"GitHub issue would've been created on github.com/{self.github_org[0]}/{self.github_repo[0]}.", file=sys.stderr, flush=False)
            if len(_tags) > 0:
                print(f"We would attempt to apply the following tags:", file=sys.stderr, flush=False)
                for tag in _tags:
                    print(f"* {tag}", file=sys.stderr, flush=False)
                print(f"We would attempt to assign the following user:", file=sys.stderr, flush=False)
                for tag in _tags:
                    if tag in self.assigneelist:
                        print(f"* {self.assigneelist[tag]}", file=sys.stderr, flush=False)

    def open_github_issue(self):
        """Macro function to assemble and open our GitHub Issue.  This wraps the title, body, and tag assembly and issue generation."""
        _message = self.generate_github_issue_body()

        _tags = self.generate_tags()
        if self.output_file is not None:
            with open(self.output_file, "w+") as f:
                f.write(_message)
        if self.consolidated_defect and not self.dry_run:
            try:
                g = Github(self.github_token)
                org = g.get_organization(self.github_org[0])
                repo = org.get_repo(self.github_repo[0])
            except UnknownObjectException as ex:
                print(f"Failed login to GitHub or find org/repo.  See error below for additional details: {ex}", file=sys.stderr, flush=False)
                exit(1)
            _github_tags_objects=[]
            for tag in _tags:
                try:
                    _github_tags_objects.append(repo.get_label(tag))
                except UnknownObjectException as ex:
                    print(f"Couldn't find GitHub Tag {tag}, skipping and continuing.", file=sys.stderr, flush=False)
                    pass
            _assignees=[]
            for tag in _tags:
                try:
                    if tag in self.assigneelist:
                        _assignees.append(GitHubIssueGenerator.get_user(org, self.assigneelist[tag]))
                except UnknownObjectException as ex:
                    print(f"No user for {tag}, skipping and continuing.", file=sys.stderr, flush=False)
                    pass
            _issue = repo.create_issue(self.generate_issue_title(), body=_message, labels=_github_tags_objects, assignees=_assignees)
            print(_issue.html_url)
        else:
            print(f"--dry-run or --no-consolidated-defect has been set, skipping consolidated git issue creation", file=sys.stderr, flush=False)
            print(f"GitHub issue would've been created on github.com/{self.github_org[0]}/{self.github_repo[0]}.", file=sys.stderr, flush=False)
            if len(_tags) > 0:
                print(f"We would attempt to apply the following tags:", file=sys.stderr, flush=False)
                for tag in _tags:
                    print(f"* {tag}", file=sys.stderr, flush=False)
                print(f"We would attempt to assign the following user:", file=sys.stderr, flush=False)
                for tag in _tags:
                    if tag in self.assigneelist:
                        print(f"* {self.assigneelist[tag]}", file=sys.stderr, flush=False)


    def generate_tags(self):
        _unique_tags = self.aggregated_results.get_unique_tags_from_failures()
        _unique_tags = [t if GitHubIssueGenerator.tag_mappings.get(t.lower(), None) is None else GitHubIssueGenerator.tag_mappings.get(t.lower(), None) for t in _unique_tags]
        _tags = list(set([*_unique_tags, *self.tags])) # Merge and find unique detected tags and user-input tags
        # Translate tag shortnames into GitHub tag values using our mappings
        _mutable_sevs = GitHubIssueGenerator.severities.copy()
        _mutable_pris = GitHubIssueGenerator.priorities.copy()
        _tags = self.filter_ordered_tags(_tags, _mutable_sevs)
        _tags = self.filter_ordered_tags(_tags, _mutable_pris)
        return _tags

    def get_user(org, user_name):
        for user in org.get_members():
            if user.login == user_name:
                return user

    def filter_ordered_tags(self, target, ordered_filter):
        """Helper function to filer an input list to include only the filter_ordered_tagshighest-indexed entry given an ordered list of priority/severity tags."""
        _highest=len(ordered_filter)
        for t in target:
            _highest = ordered_filter.index(t) if t in ordered_filter and ordered_filter.index(t) < _highest else _highest
        if _highest < len(ordered_filter):
            ordered_filter.remove(ordered_filter[_highest])
            _filtered_target = [t for t in target if t not in ordered_filter]
            return _filtered_target
        else:
            return target


    def generate_github_issue_body(self):
        """Macro function to assemble our GitHub Issue.  This wraps the header, metadata, summary, and body generation with a neat bow."""
        # Generate GitHub Issue Test
        _report = ""
        _report = _report + self.generate_header() + "\n"
        _report = _report + self.generate_metadata() + "\n"
        _report = _report + self.generate_summary() + "\n"
        _report = _report + self.generate_body() + "\n"
        # Create GitHub Issue with generated report body
        return _report


    def generate_issue_title(self):
        """Macro function to assemble our GitHub Issue title, handling with any combination of optional vars."""
        _header = ""
        if self.branch is not None:
            _header = _header + f"[{self.branch.capitalize()}] "
        _header = _header + f"CICD Canary Build Failure"
        if self.snapshot is not None:
            _header = _header + f" for {self.snapshot}"
        if self.stage is not None:
            _header = _header + f" During the {self.stage.capitalize()} Stage"
        return _header


    def generate_header(self):
        """Macro function to assemble our GitHub Issue header, handling with any combination of optional vars."""
        _status = self.aggregated_results.get_status(executed_gate=self.executed_quality_gate, passing_gate=self.passing_quality_gate)
        _header = f"# {GitHubIssueGenerator.header_symbols[_status]}"
        if self.snapshot is not None:
            _header = _header + self.snapshot
        _header = _header + f" {_status.capitalize()}"
        if self.stage is not None:
            _header = _header + f" on branch {self.stage.capitalize()}"
        return _header

    
    def generate_metadata(self):
        """Generates a metadata string for our GitHub Issue containing all links and metadata given in optional vars."""
        _metadata = ""
        # Add a link to the CI Job
        if self.job_url is not None:
            _metadata = _metadata + f"## Job URL: {self.job_url}\n"
        if (self.sd_url is not None or self.hub_version is not None or self.import_cluster_details is not []
            or self.mg_url is not None or self.results_url is not None):
            _metadata = _metadata + f"## Artifacts & Details\n"
            # Add a link to the s3 buckets for results and must-gather
            if self.mg_url is not None:
                _metadata = _metadata + f"[**Must-Gather Bucket**]({self.mg_url})\n\n"
            if self.results_url is not None:
                _metadata = _metadata + f"[**Results Bucket**]({self.results_url})\n\n"
            # Include a link to the git issue where available
            if self.md_url is not None:
                _metadata = _metadata + f"[**Markdown Report**]({self.md_url})\n\n"
            # Add a link to the snapshot diff
            if self.sd_url is not None:
                _metadata = _metadata + f"[**Snapshot Diff**]({self.sd_url})\n\n"
            # Add hub cluster details where available
            if self.hub_platform is not None and self.hub_version is not None:
                _metadata = _metadata + f"**Hub Cluster Platform:** {self.hub_platform}    **Hub Cluster Version:** {self.hub_version}\n\n"
            elif self.hub_version is not None:
                _metadata = _metadata + f"**Hub Cluster Version:** {self.hub_version}\n\n"
            elif self.hub_platform is not None:
                _metadata = _metadata + f"**Hub Cluster Platform:** {self.hub_platform}\n\n"
            # Add import cluster details where available
            if len(self.import_cluster_details) > 0:
                _metadata = _metadata + f"**Import Cluster(s):**\n"
            for import_cluster in self.import_cluster_details:
                if import_cluster['platform'] is not None and import_cluster["version"] is not None:
                    _metadata = _metadata + f"* **Import Cluster Platform:** {import_cluster['platform']}    **Import Cluster Version:** {import_cluster['version']}\n"
                elif import_cluster['version'] is not None:
                    _metadata = _metadata + f"* **Import Cluster Version:** {import_cluster['version']}\n"
                elif import_cluster['platform']:
                    _metadata = _metadata + f"* **Import Cluster Platform:** {import_cluster['platform']}\n"
            _metadata = _metadata + "\n"
        return _metadata


    def generate_summary(self):
        """Generates a summary of our test results including gating percentages and pass/fail/skip/ignored results as available."""
        _total, _passed, _failed, _skipped, _ignored = self.aggregated_results.get_counts()
        _coverage = self.aggregated_results.get_coverage()
        _percentage_exectued = round(_coverage[ra.ResultsAggregator.skipped], 2)
        _percentage_passing = round(_coverage[ra.ResultsAggregator.passed], 2) # Note - percentage of executed tests, ignoring skipped tests
        # Determine icon for our percentage executed gate
        if _percentage_exectued >= self.executed_quality_gate:
            # Mark with passing if it fully meets quality gates
            _executed_icon = GitHubIssueGenerator.quality_symbols[ra.ResultsAggregator.passed]
        elif _percentage_exectued >= (self.executed_quality_gate * .8):
            # Mark with a warning if 80% of gates or above
            _executed_icon = GitHubIssueGenerator.quality_symbols[ra.ResultsAggregator.ignored]
        else:
            # If less than 80% of quality gate, mark as red
            _executed_icon = GitHubIssueGenerator.quality_symbols[ra.ResultsAggregator.failed]
        # Determine icon for our percentage passing gate
        if _percentage_passing >= self.executed_quality_gate:
            # Mark with passing if it fully meets quality gates
            _passing_icon = GitHubIssueGenerator.quality_symbols[ra.ResultsAggregator.passed]
        elif _percentage_passing >= (self.executed_quality_gate * .8):
            # Mark with a warning if 80% of gates or above
            _passing_icon = GitHubIssueGenerator.quality_symbols[ra.ResultsAggregator.ignored]
        else:
            # If less than 80% of quality gate, mark as red
            _passing_icon = GitHubIssueGenerator.quality_symbols[ra.ResultsAggregator.failed]
        _summary = f"## Quality Gate\n\n"
        _summary = _summary + f"{_executed_icon} **Percentage Executed:** {_percentage_exectued}% ({self.executed_quality_gate}% Quality Gate)\n\n"
        _summary = _summary + f"{_passing_icon} **Percentage Passing:** {_percentage_passing}% ({self.passing_quality_gate}% Quality Gate)\n\n"
        _summary = _summary + "## Summary\n\n"
        _summary = _summary + f"**{GitHubIssueGenerator.status_symbols[ra.ResultsAggregator.passed]} {_passed} " + ("Test" if _passed == 1 else "Tests") + " Passed**\n\n"
        _summary = _summary + f"**{GitHubIssueGenerator.status_symbols[ra.ResultsAggregator.failed]} {_failed} "  + ("Test" if _failed == 1 else "Tests") + " Failed**\n\n"
        _summary = _summary + f"**{GitHubIssueGenerator.status_symbols[ra.ResultsAggregator.ignored]} {_ignored} " + ("Failure" if _ignored == 1 else "Failures") +  " Ignored**\n\n"
        _summary = _summary + f"**{GitHubIssueGenerator.status_symbols[ra.ResultsAggregator.skipped]} {_skipped} Test " + ("Case" if _skipped == 1 else "Cases") + " Skipped**\n\n"
        return _summary

    
    def generate_body(self):
        """Generates a summary of our failing tests and their console/error messages."""
        _body = ""
        _total, _passed, _failed, _skipped, _ignored = self.aggregated_results.get_counts()
        if _failed > 0:
            _body = "## Failing Tests\n\n"
            _results = self.aggregated_results.get_results()
            for _result in _results:
                if _result['state'] == ra.ResultsAggregator.failed or _result['state'] == ra.ResultsAggregator.ignored:
                    _body = _body + f"### {GitHubIssueGenerator.status_symbols[_result['state']]} {_result['testsuite']} -> {_result['name']}\n\n"
                    _body = _body + f"```\n{_result['metadata']['message']}\n```\n"
        return _body
    
