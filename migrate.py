#!/usr/bin/env python3
# encoding: utf-8

"""
Migrate Trac tickets to GitHub Issues
"""

from itertools import chain
from datetime import datetime
from getpass import getpass, getuser
from time import mktime, sleep
from urllib.parse import urljoin, urlsplit, urlunsplit
from warnings import warn
import argparse
import json
import re
import subprocess
import sys
import xmlrpc.client

from github import Github, GithubObject


def convert_value_for_json(obj):
    """Converts all date-like objects into ISO 8601 formatted strings for JSON"""

    if hasattr(obj, 'timetuple'):
        return datetime.fromtimestamp(mktime(obj.timetuple())).isoformat()
    elif hasattr(obj, 'isoformat'):
        return obj.isoformat()
    else:
        return obj


def sanitize_url(url):
    scheme, netloc, path, query, fragment = urlsplit(url)

    if '@' in netloc:
        # Strip HTTP basic authentication from netloc:
        netloc = netloc.rsplit('@', 1)[1]

    return urlunsplit((scheme, netloc, path, query, fragment))


def make_blockquote(text):
    return re.sub(r'^', '> ', text, flags=re.MULTILINE)


class HTTPSDigestTransport(xmlrpc.client.SafeTransport):
    """
    Transport that uses urllib2 so that we can do Digest authentication.

    Based upon code at http://bytes.com/topic/python/answers/509382-solution-xml-rpc-over-proxy
    """

    def __init__(self, username, pw, realm, verbose = None, use_datetime=0):
        self.__username = username
        self.__pw = pw
        self.__realm = realm
        self.verbose = verbose
        self._use_datetime = use_datetime

    def request(self, host, handler, request_body, verbose):
        import urllib.request, urllib.error, urllib.parse

        url = 'https://'+host+handler
        if verbose or self.verbose:
            print("ProxyTransport URL: [%s]" % url)

        request = urllib.request.Request(url)
        request.add_data(request_body)
        # Note: 'Host' and 'Content-Length' are added automatically
        request.add_header("User-Agent", self.user_agent)
        request.add_header("Content-Type", "text/xml") # Important

        # setup digest authentication
        authhandler = urllib.request.HTTPDigestAuthHandler()
        authhandler.add_password(self.__realm, url, self.__username, self.__pw)
        opener = urllib.request.build_opener(authhandler)

        # proxy_handler = urllib2.ProxyHandler()
        # opener = urllib2.build_opener(proxy_handler)
        f = opener.open(request)
        return(self.parse_response(f))


class Migrator():
    def __init__(self, trac_url=None, trac_realm=None, trac_username=None, trac_password=None, trac_filter=None,
                 github_username=None, github_password=None, github_project=None, github_api_url=None,
                 username_map=None):
        trac_api_url = trac_url + "/login/rpc"
        print("TRAC api url: %s" % trac_api_url, file=sys.stderr)

        if trac_realm:
            digestTransport = HTTPSDigestTransport(trac_username, trac_password, trac_realm)
            self.trac = xmlrpc.client.ServerProxy(trac_api_url, transport=digestTransport)
        else:
            trac_api_url = trac_api_url.replace("://", "://USERNAME:PASSWORD@")
            trac_api_url = trac_api_url.replace("USERNAME", trac_username).replace("PASSWORD", trac_password)
            self.trac = xmlrpc.client.ServerProxy(trac_api_url)
        self.trac_public_url = sanitize_url(trac_url)
        self.trac_filter = trac_filter

        self.github = gh = Github(github_username, github_password, base_url=github_api_url)
        self.github_repo = self.github.get_repo(github_project)

        print("Building trac<->github username map...")
        self.username_map = {i: gh.get_user(j) for i, j in list(username_map.items())}

    def convert_ticket_id(self, trac_id):
        trac_id = int(trac_id)
        if trac_id in self.trac_issue_map:
            return "#%s" % self.trac_issue_map[trac_id].number
        else:
            return urljoin(self.trac_public_url, 'ticket/%d' % trac_id)

    def fix_wiki_syntax(self, markup):
        markup = re.sub(r'(?:refs #?|#)(\d+)', lambda i: self.convert_ticket_id(i.group(1)),
                        markup)
        markup = re.sub(r'#!CommitTicketReference.*rev=([^\s]+)\n', lambda i: i.group(1),
                        markup, flags=re.MULTILINE)

        markup = markup.replace("{{{\n", "\n```text\n")
        markup = markup.replace("{{{", "```")
        markup = markup.replace("}}}", "```")

        markup = markup.replace("[[BR]]", "\n")

        markup = re.sub(r'\[changeset:"([^"/]+?)(?:/[^"]+)?"]', r"changeset \1", markup)

        return markup

    def get_gh_milestone(self, milestone):
        if milestone:
            if milestone not in self.gh_milestones:
                m = self.github_repo.create_milestone(milestone)
                self.gh_milestones[m.title] = m

            return self.gh_milestones[milestone]
        else:
            return GithubObject.NotSet

    def get_gh_label(self, label):
        if label not in self.gh_labels:
            self.gh_labels[label] = self.github_repo.create_label(label, color='FFFFFF')
        return self.gh_labels[label]

    def run(self):
        self.load_github()
        self.migrate_tickets()

    def load_github(self):
        print("Loading information from GitHub…", file=sys.stderr)

        repo = self.github_repo
        print("    ... milestones", file=sys.stderr)
        self.gh_milestones = {i.title: i for i in chain(repo.get_milestones(),
                                                        repo.get_milestones(state="closed"))}
        print("    ... labels", file=sys.stderr)
        self.gh_labels = {i.name: i for i in repo.get_labels()}
        print("    ... issues", file=sys.stderr)
        self.gh_issues = {i.title: i for i in chain(repo.get_issues(state="open"),
                                                    repo.get_issues(state="closed"))}

    def get_github_username(self, trac_username):
        if trac_username in self.username_map:
            return self.username_map[trac_username]
        else:
            #warn("Cannot map Trac username >{0}< to GitHub user. Will add username >{0}< as label.".format(trac_username))
            return GithubObject.NotSet

    def migrate_tickets(self):
        print("Loading information from Trac…", file=sys.stderr)

        get_all_tickets = xmlrpc.client.MultiCall(self.trac)

        for ticket in self.trac.ticket.query(self.trac_filter):
            get_all_tickets.ticket.get(ticket)

        # Take the memory hit so we can rewrite ticket references:
        all_trac_tickets = list(get_all_tickets())
        self.trac_issue_map = trac_issue_map = {}

        # this is the first pass across the tickets, creating the ticket,
        # milestones, labels and assignees
        print ("Creating GitHub tickets…", file=sys.stderr)
        for trac_id, time_created, time_changed, attributes in all_trac_tickets:
            title = "%s (Trac #%d)" % (attributes['summary'], trac_id)

            # Intentionally do not migrate description at this point so we can rewrite
            # ticket ID references after all tickets have been created in the second pass below:

            # build up some vars which will fill our fancy ticket "template" below
            trac_ticket_url = urljoin(self.trac_public_url, "ticket/%d" % trac_id)
            text_attributes = {k: convert_value_for_json(v) for k, v in list(attributes.items())}
            trac_ticket_reporter = attributes['reporter'].strip()  # trac ticket reporter
            trac_ticket_owner    = attributes['owner'].strip()     # trac ticket owner

            if trac_ticket_reporter:
                ownership = f", reported by {trac_ticket_owner}"
            if not trac_ticket_reporter and trac_ticket_owner:
                ownership = f", owned by {trac_ticket_owner}"
            if trac_ticket_reporter and trac_ticket_owner:
                ownership = f", reported by {trac_ticket_owner} and owned by {trac_ticket_owner}"

            # this is our fancy ticket template. note it doesn't include details.
            # they get prepended during the second pass below
            body = f"""\
            <details>
            <summary><em>Migrated from <a href="{trac_ticket_url}">{trac_ticket_url}</a>{ownership}</em></summary>
            <p>

            ```json
            {json.dumps(text_attributes, indent=4)}
            ```

            </p>
            </details>
            """

            milestone = self.get_gh_milestone(attributes['milestone'])

            assignee = self.get_github_username(attributes['owner'])

            labels = ['Migrated from Trac', 'Incomplete Migration']

            # User does not exist in GitHub -> Add username as label
            if (assignee is GithubObject.NotSet and (attributes['owner'] and attributes['owner'].strip())):
                #labels.extend([attributes['owner']])
                pass

            labels.extend([_f for _f in (attributes['type'], attributes['component']) if _f])
            labels = list(map(self.get_gh_label, labels))

            for i, j in list(self.gh_issues.items()):
                if i == title:
                    gh_issue = j
                    if (assignee is not GithubObject.NotSet and
                        (not gh_issue.assignee
                         or (gh_issue.assignee.login != assignee.login))):
                        gh_issue.edit(assignee=assignee)
                    break
            else:
                gh_issue = self.github_repo.create_issue(title, assignee=assignee, body=body,
                                                         milestone=milestone, labels=labels)
                self.gh_issues[title] = gh_issue
                print ("\tCreated issue: %s (%s)" % (title, gh_issue.html_url), file=sys.stderr)

                sleep(10)
                if not (trac_id % 150):
                    print("Sleeping 300s before ticket #{}".format(trac_id))
                    sleep(300)

            trac_issue_map[int(trac_id)] = gh_issue

        # this is the second pass across the tickets, creating descriptions and comments
        print("Migrating descriptions and comments…", file=sys.stderr)

        incomplete_label = self.get_gh_label('Incomplete Migration')

        for trac_id, time_created, time_changed, attributes in all_trac_tickets:
            gh_issue = trac_issue_map[int(trac_id)]

            if incomplete_label.url not in [i.url for i in gh_issue.labels]:
                continue

            sleep(10)
            if not (trac_id % 150):
                print("Sleeping 300s before ticket #{}".format(trac_id))
                sleep(300)

            gh_issue.remove_from_labels(incomplete_label)

            print("\t%s (%s)" % (gh_issue.title, gh_issue.html_url), file=sys.stderr)

            gh_issue.edit(body="%s\n\n%s" % (self.fix_wiki_syntax(attributes['description']), gh_issue.body))

            changelog = self.trac.ticket.changeLog(trac_id)

            comments = {}

            for time, author, field, old_value, new_value, permanent in changelog:
                if field == 'comment':
                    if not new_value:
                        continue
                    body = '%s commented:\n\n%s\n\n' % (author,
                                                        make_blockquote(self.fix_wiki_syntax(new_value)))
                else:
                    if "\n" in old_value or "\n" in new_value:
                        body = '%s changed %s from:\n\n%s\n\nto:\n\n%s\n\n' % (author, field,
                                                                           make_blockquote(old_value),
                                                                           make_blockquote(new_value))
                    else:
                        body = '%s changed %s from "%s" to "%s"' % (author, field, old_value, new_value)

                comments.setdefault(time.value, []).append(body)

            for time, values in sorted(comments.items()):
                if len(values) > 1:
                    fmt = "\n* %s" % "\n* ".join(values)
                else:
                    fmt = "".join(values)

                gh_issue.create_comment("Trac update at %s: %s" % (time, fmt))

            if attributes['status'] == "closed":
                gh_issue.edit(state="closed")


def check_simple_output(*args, **kwargs):
    return "".join(subprocess.check_output(shell=True, *args, **kwargs)).strip()


def get_github_credentials():
    github_username = getuser()
    github_password = None
    github_token = None

    try:
        github_username = check_simple_output('git config --get github.user')
    except subprocess.CalledProcessError:
        pass

    if not github_password:
        try:
            github_password = check_simple_output('git config --get github.password')
            if github_password.startswith("!"):
                github_password = check_simple_output(github_password.lstrip('!'))
        except subprocess.CalledProcessError:
            pass

    try:
        github_token = check_simple_output('git config --get github.token')
    except subprocess.CalledProcessError:
        pass

    return github_username, github_password, github_token


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    github_username, github_password, github_token = get_github_credentials()

    parser.add_argument('--trac-url',
                        action="store",
                        required=True,
                        help="Trac base URL")

    parser.add_argument('--github-project',
                        action="store",
                        required=True,
                        help="GitHub Project: e.g. username/project")

    parser.add_argument('--trac-realm',
                        action="store",
                        default=None,
                        help="Trac realm for Digest auth (default: %(default)s)")

    parser.add_argument('--trac-username',
                        action="store",
                        default=None,
                        help="Trac username (default: %(default)s)")

    parser.add_argument('--trac-filter',
                        action="store",
                        default="max=0&order=id",
                        help="Trac ticket filter (default: %(default)s)")

    parser.add_argument('--github-token',
                        action="store",
                        default=github_token,
                        help="GitHub token (default: %(default)s)")

    parser.add_argument('--github-username',
                        action="store",
                        default=github_username,
                        help="GitHub username (default: %(default)s)")

    parser.add_argument('--github-api-url',
                        action="store",
                        default="https://api.github.com",
                        help="GitHub API URL (default: %(default)s)")

    parser.add_argument('--username-map',
                        type=argparse.FileType('r'),
                        help="File containing tab-separated Trac:GitHub username mappings")

    args = parser.parse_args()

    if not args.trac_url:
        parser.error("Trac URL must be specified")
    if not args.github_project:
        parser.error("GitHub Project must be specified")

    trac_username = args.trac_username
    if not trac_username:
        trac_username = input("Trac username: ")
    trac_password = getpass("Trac password: ")

    if not github_password and not github_token:
        github_password = getpass("GitHub password: ")

    if github_token:
        github_username = github_token

    try:
        import bpdb as pdb
    except ImportError:
        import pdb

    if args.username_map:
        user_map = [_f for _f in (i.strip() for i in args.username_map.readlines()) if _f]
        user_map = [re.split("\s+", j, maxsplit=1) for j in user_map]
        user_map = dict(user_map)
    else:
        user_map = {}

    m = Migrator(
        trac_url=args.trac_url,
        trac_realm=args.trac_realm,
        trac_username=trac_username,
        trac_password=trac_password,
        trac_filter=args.trac_filter,
        github_username=github_username,
        github_password=github_password,
        github_api_url=args.github_api_url,
        github_project=args.github_project,
        username_map=user_map)
    m.run()
