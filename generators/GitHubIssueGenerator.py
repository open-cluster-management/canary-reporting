"""GitHubIssueGenerator

An AbstractGenerator and ReportGenerator implementation to generate a markdown report as part of the canary reporting CLI.  
This class can generate its CLI parser, load args, generate a ResultsAggregator object, and format the output data as a md report. 
"""

import os, sys, json, argparse
from github import Github, UnknownObjectException
from generators import AbstractGenerator,ReportGenerator
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from datamodel import ResultsAggregator as ra

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

    def __init__(self, results_dirs, snapshot=None, branch=None, stage=None, hub_version=None, 
        hub_platform=None, import_version=None, import_platform=None, job_url=None, build_id=None,
        sd_url=None, md_url=None, must_gather_url=None, results_url=None, ignorelist=[], 
        passing_quality_gate=100, executed_quality_gate=100, github_token=os.getenv('GITHUB_TOKEN'), github_org=["open-cluster-management"],
        github_repo=["cicd-staging"], tags=[], dry_run=True, output_file="github.md"):
        """Create a GitHubIssueGenerator Object, unroll xml files from input, and initialize a ResultsAggregator.  

        Required Arguments:
        results_dirs    -- a list of directories that contain XML files from which to generate an aggregate report

        Keyword Arguments:
        snapshot    --  a string representation of the snapshot that these test results represent, ex. 2.2.0-SNAPSHOT-timestamp
        branch      --  a string representaiton of the integration test branch that generated the xml results, ex. 2.2-integration
        stage       --  a string representaiton of the integration test stage/step that generated the xml results, ex deploy
        hub_version     --  a string representation of the hub cluster version that was tested
        hub_platform    --  a string representation of the hub cluster's hosting cloud platform
        import_version  --  a string representation of the import cluster version that was tested
        import_platform --  a string representation of the import cluster's hosting cloud platform
        job_url     --  the URL of the CI job that produced this JUnit XML, ex. $TRAVIS_BUILD_WEB_URL
        build_id    --  CI build id (unique identifier) that produced this JUnit XML, ex. $TRAVIS_BUILD_ID
        sd_url      --  the URL of any snapshot diff report generated previously for this snapshot
        md_url      --  the URL of any hosted md report generated previously from this XML
        must_gather_url     --  the URL of an s3 bucket containing must-gather data from this test
        results_url         --  the URL of an s3 bucket containing the raw XML results from this test
        ignorelist          --  a list of dicts contianing "name", "squad", and "owner" keys
        passing_quality_gate    --  a number between 0 and 100 that defines the percentage of tests that must pass to declare success
        executed_quality_gate   --  a number between 0 and 100 that defines the percentage of tests that must be executed to declare success
        github_token    --  the user's github token used to access/create the GitHub issue - loaded from the GITHUB_TOKEN env var if not set
        github_org      --  the github organization where the git issue should be created
        github_repo     --  the github repo where the git issue should be created
        tags    --  a list of github tags that should be applied to the git issue
        dry_run --  toggles actual github creation - if present an issue will not actually be created, but we'll run through the paces
        output_file --  a place to output the git issue's raw markdown, especially useful when using dry-run
        """
        self.snapshot = snapshot
        self.branch = branch
        self.stage = stage
        self.hub_version = hub_version
        self.hub_platform = hub_platform
        self.import_version = import_version
        self.import_platform = import_platform
        self.job_url = job_url
        self.build_id = build_id
        self.sd_url = sd_url
        self.md_url = md_url
        self.mg_url = must_gather_url
        self.results_url = results_url
        self.ignorelist = ignorelist
        self.passing_quality_gate = passing_quality_gate
        self.executed_quality_gate = executed_quality_gate
        self.results_files = []
        self.github_token = github_token
        self.github_org = github_org
        self.github_repo = github_repo
        self.tags = tags
        self.dry_run = dry_run
        self.output_file = output_file
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
        gh_parser.add_argument('--github-token', nargs=1, default=os.getenv('GITHUB_TOKEN'),
            help="GitHub token for access to create GitHub issues.  Pulls from teh GITHUB_TOKEN environment variable if not specified.")
        gh_parser.add_argument('-eg', '--executed-quality-gate', default='100',
            help="Percentage of the test suites that must be executed (not skipped) to count as a quality result.")
        gh_parser.add_argument('-pg', '--passing-quality-gate', default='100',
            help="Percentage of the executed test cases that must pass to count as a quality result.")
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
            help="If provided - an actual GitHub issue will not be created, but the file will be generated, best used with -o.")
        gh_parser.add_argument('-t', '--tags', action='append',
            help="GitHub issue tags to apply to the created issue.  Only applied if the tags exist on the target repository.")
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
                print(f"Ignorelist found in {args.ignore_list} was not in JSON format, ignoring the ignorelist. Ironic.")
        _generator = GitHubIssueGenerator(args.results_directory, snapshot=args.snapshot, branch=args.branch, stage=args.stage,
            hub_version=args.hub_version, hub_platform=args.hub_platform, import_version=args.import_version, import_platform=args.import_platform,
            job_url=args.job_url, build_id=args.build_id, ignorelist=_ignorelist, sd_url=args.snapshot_diff_url,
            md_url=args.markdown_url, executed_quality_gate=int(args.executed_quality_gate), passing_quality_gate=int(args.passing_quality_gate),
            results_url=args.results_url, must_gather_url=args.must_gather_url, github_token=args.github_token, github_org=args.github_organization,
            github_repo=args.repo, tags=args.tags, dry_run=args.dry_run, output_file=args.output_file)
        _message = _generator.open_github_issue()

    
    def open_github_issue(self):
        """Macro function to assemble and open our GitHub Issue.  This wraps the title, body, and tag assembly and issue generation."""
        _message = self.generate_github_issue_body()
        if self.output_file is not None:
            with open(self.output_file, "w+") as f:
                f.write(_message)
        if not self.dry_run:
            try:
                g = Github(self.github_token)
                org = g.get_organization(self.github_org[0])
                repo = org.get_repo(self.github_repo[0])
            except UnknownObjectException as ex:
                print("Failed login to GitHub or find org/repo.  See error below for additional details:")
                print(ex)
                exit(1)
            _tags = []
            if self.tags:
                for tag in self.tags:
                    try:
                        _tags.append(repo.get_label(tag))
                    except UnknownObjectException as ex:
                        print(f"Couldn't find GitHub Tag {tag}, skipping and continuing.")
                        pass
            _issue = repo.create_issue(self.generate_issue_title(), body=_message, labels=_tags)
            print(_issue.html_url)
        else:
            print("--dry-run as been set, skipping git issue creation")
            print(f"GitHub issue would've been created on github.com/{self.github_org[0]}/{self.github_repo[0]}.")
            if self.tags:
                print("We would attempt to apply the following tags:")
                for tag in self.tags:
                    print(f"* {tag}")

    
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
        _status = self.aggregated_results.get_status()
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
        if (self.sd_url is not None or self.hub_version is not None or self.import_version is not None
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
            if self.import_platform is not None and self.import_version is not None:
                _metadata = _metadata + f"**Import Cluster Platform:** {self.import_platform}    **Import Cluster Version:** {self.import_version}\n\n"
            elif self.import_version is not None:
                _metadata = _metadata + f"**Import Cluster Version:** {self.import_version}\n\n"
            elif self.import_platform is not None:
                _metadata = _metadata + f"**Import Cluster Platform:** {self.import_platform}\n\n"
        return _metadata


    def generate_summary(self):
        """Generates a summary of our test results including gating percentages and pass/fail/skip/ignored results as available."""
        _total, _passed, _failed, _skipped, _ignored = self.aggregated_results.get_counts()
        _percentage_exectued = round(100 - ((_skipped / _total) * 100))
        _percentage_passing = round((_passed / (_total - _skipped)) * 100) # Note - percentage of executed tests, ignoring skipped tests
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
        _total, _passed, _failed, _skipped, _ignored = self.aggregated_results.get_counts()
        _summary = _summary + "## Summary\n\n"
        _summary = _summary + f"**{GitHubIssueGenerator.status_symbols[ra.ResultsAggregator.passed]} {_passed} " + ("Test" if _passed == 1 else "Tests") + " Passed**\n\n"
        _summary = _summary + f"**{GitHubIssueGenerator.status_symbols[ra.ResultsAggregator.failed]} {_failed} "  + ("Test" if _failed == 1 else "Tests") + " Failed**\n\n"
        _summary = _summary + f"**{GitHubIssueGenerator.status_symbols[ra.ResultsAggregator.ignored]} {_ignored} " + ("Failure" if _ignored == 1 else "Failures") +  " Ignored**\n\n"
        _summary = _summary + f"**{GitHubIssueGenerator.status_symbols[ra.ResultsAggregator.skipped]} {_skipped} Test " + ("Case" if _skipped == 1 else "Cases") + " Skipped**\n\n"
        return _summary

    
    def generate_body(self):
        """Generates a summary of our failing tests and their console/error messages."""
        _body = "## Failing Tests\n\n"
        _results = self.aggregated_results.get_results()
        for _result in _results:
            if _result['state'] == ra.ResultsAggregator.failed or _result['state'] == ra.ResultsAggregator.ignored:
                _body = _body + f"### {GitHubIssueGenerator.status_symbols[_result['state']]} {_result['testsuite']} -> {_result['name']}\n\n"
                _body = _body + f"```\n{_result['metadata']['message']}\n```\n"
        return _body
    
