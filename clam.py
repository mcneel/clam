"""
    clam
    ~~~

    Yet another Contributor License Agreement Manager with webhooks and whatnot.

    :copyright: (c) 2015 by Will Pearson, Robert McNeel & Associates
    :license: MIT, see LICENSE for more details.
"""

__version__ = '0.1-dev'

from flask import Flask, request
from flask.ext.sqlalchemy import SQLAlchemy
import json
from os import environ
import requests

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = environ.get('DATABASE_URL', 'sqlite:///db.sqlite')
app.config['DEBUG'] = environ.get('DEBUG', False)
db = SQLAlchemy(app)

class Signatory(db.Model):
    __tablename__ = 'signatories'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(), index=True)
    version = db.Column(db.String())
    full_name = db.Column(db.String())
    email = db.Column(db.String())
    address = db.Column(db.String())
    telephone = db.Column(db.String())

@app.route('/')
def hello():
    return 'Hello World!'

def get_pull_request_authors(repo, pr):
    """Gets a list of committers for a given pull request"""
    app.logger.debug('getting committers for {} #{}'.format(repo, pr))
    url = 'https://api.github.com/repos/{}/pulls/{}/commits'
    r = requests.get(url.format(repo, pr))
    committers = [c['committer']['login'] for c in r.json()]
    # reduce committers to unique set
    committers = list(set(committers))
    app.logger.debug('committers for #{}: '.format(pr) + ','.join(committers))
    return committers

status_context = 'ci/clam'

def set_commit_status(repo, sha, status):
    state = ''
    desciption = ''
    if status:
        state = 'success'
        description = 'All contributors have signed the CLA!'
    else:
        state = 'failure'
        description = 'Not all contributors have signed the CLA'

    payload = {
        'state': state,
        #'target_url': link_to_agreement,
        'description': description,
        'context': status_context
    }

    url = 'https://api.github.com/repos/{}/statuses/{}'

    # debug
    app.logger.debug(url.format(repo, sha))
    app.logger.debug(json.dumps(payload))

    # set status
    auth = {'Authorization': 'token ' + environ.get('CLAM_GITHUB_TOKEN')}
    r = requests.post(url.format(repo, sha), data=json.dumps(payload), headers=auth)

    # debug
    app.logger.debug((r.status_code, r.json()))

def get_commit_status(repo, sha, status):
    """Returns True if commit status is already 'success', otherwise False"""
    url = 'https://api.github.com/repos/{}/commits/{}/statuses'
    r = requests.get(url.format(repo, sha))
    for status in r.json():
        if status['context'] == status_context:
            return status['state'] == success
    return False

def user_in_org(user):
    # https://developer.github.com/v3/orgs/#list-user-organizations
    url = 'https://api.github.com/users/{}/orgs'.format(user)
    r = requests.get(url)
    for org in r.json():
        if org['login'] == environ.get('CLAM_GITHUB_ORG'):
            app.logger.debug('{} in {}; CLA not required'.format(user, org['login']))
            return True
    app.logger.debug('{} not in {}'.format(user, environ.get('CLAM_GITHUB_ORG')))
    return False

def user_is_collaborator(user, repo):
    # https://developer.github.com/v3/repos/collaborators/
    # GET /repos/:owner/:repo/collaborators
    url = 'https://api.github.com/repos/{}/collaborators'.format(repo)
    auth = {'Authorization': 'token ' + environ.get('CLAM_GITHUB_TOKEN')}
    r = requests.get(url, headers=auth)
    collaborators = [c['login'] for c in r.json()]
    if user in collaborators:
        app.logger.debug('{} is has push access to {}, CLA not required'.format(user, repo))
        return True
    else:
        return False

@app.route('/_github', methods=['POST'])
def github():
    """endpoint for handling pull_request webhook events"""
    # ignore anything that isn't a pull_request
    if request.headers.get('X-GitHub-Event') == 'pull_request':
        pull = request.get_json()

        # ignore pull_request event if not 'opened' or 'sync' (i.e. new commits)
        if pull['action'] not in ['opened', 'synchronize', 'reopened']:
            app.logger.debug('ignoring pull_request action: ' + pull['action'])
            return 'ignoring pull_request action: {}\n'.format(pull['action']), 200

        # get heah sha - pull request uses this commit status
        head = pull['pull_request']['head']['sha']

        # get authors
        repo = pull['repository']['full_name'] # owner/repo
        number = pull['number']
        authors = get_pull_request_authors(repo, number)

        for author in authors:
            # check org + collaborators
            if user_in_org(author):
                set_commit_status(repo, head, True)
                return '', 200
                #pass
            if user_is_collaborator(author, repo):
                set_commit_status(repo, head, True)
                return '', 200
                #pass
            # check signatories
            if not Signatory.query.filter_by(username=author).first():
                app.logger.debug('{} hasn\'t signed yet'.format(author))
                set_commit_status(repo, head, False)
                return 'commit status set\n', 200
            app.logger.debug('{} has already signed'.format(author))
        set_commit_status(repo, head, True)
        return 'commit status set\n', 200
    else:
        return 'nothing to do\n', 200


# TODO: when someone signs the CLA, re-check all open pull requests
# GET /repos/:owner/:repo/pulls?state=open
# GET /repos/:owner/:repo/pulls/:number/commits


if __name__ == '__main__':
    import os
    if not os.path.exists('db.sqlite'):
        db.create_all()
    app.run(debug=True)
