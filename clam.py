"""
    clam
    ~~~

    Yet another Contributor License Agreement Manager with webhooks and whatnot.

    :copyright: (c) 2015 by Will Pearson, Robert McNeel & Associates
    :license: MIT, see LICENSE for more details.
"""

__version__ = '0.1-dev'

from flask import Flask, flash, make_response, redirect, render_template, request, session, url_for
from flask.ext.sqlalchemy import SQLAlchemy
from jinja2 import Markup
import json
import markdown
from os import environ
import requests

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = environ.get('DATABASE_URL', 'sqlite:///db.sqlite')
app.config['DEBUG'] = environ.get('DEBUG', False)
app.config['SECRET_KEY'] = 'I can see a dark green jeep from my window radish barracuda'

db = SQLAlchemy(app)

class Signatory(db.Model):
    __tablename__ = 'signatories'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(), unique=True)
    version = db.Column(db.String())
    full_name = db.Column(db.String())
    email = db.Column(db.String())
    address = db.Column(db.String())
    telephone = db.Column(db.String())

    def to_json(self):
        return {
            'github_user': self.username,
            'cla_version': self.version,
            'full_name': self.full_name,
            'email': self.email,
            'address': self.address,
            'telephone': self.telephone
        }

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
    state = 'success' if status else 'failure'
    desciption = ''
    target_url = ''
    if status:
        description = 'All contributors have signed the CLA!'
        target_url = url_for('sign', _external=True)
    else:
        description = 'Not all contributors have signed the CLA'
        target_url = url_for('sign', _external=True)

    payload = {
        'state': state,
        'target_url': target_url,
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
    if r.status_code != requests.codes.ok:
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

from wtforms import Form, StringField, TextAreaField, BooleanField, validators

class RegistrationForm(Form):
    username = None
    full_name = StringField('Full Name', [validators.Length(min=4, max=25)])
    email = StringField('Email Address', [validators.Length(min=6, max=35), validators.Email()])
    address = TextAreaField('Address')
    telephone = StringField('Phone Number')
    cla_version = StringField('CLA Version')
    accept = BooleanField('I accept', [validators.Required()])
    redirect = None

def get_cla_and_version():
    path = 'CLA'

    # TODO: set repo in env var
    repo = 'mcneel/clam'

    # content
    url = 'https://api.github.com/repos/{}/contents/'.format(repo)
    r = requests.get(url)
    content = None
    for f in r.json():
        name = f['name'].split('.')
        if name[0].upper() == path:
            path = '.'.join(name)
            app.logger.debug("found file: " + path)
            # get contents (use github to render html = genius!)
            url = 'https://api.github.com/repos/{}/contents/{}'.format(repo, path)
            media={'Accept':'application/vnd.github.VERSION.html'}
            r = requests.get(url, headers=media)
            content = Markup(r.text)
            break
    if not content:
        app.logger.error('couldn\'t find CLA in repository, did you forget to commit it?')

    # sha
    url = 'https://api.github.com/repos/{}/commits?path={}'.format(repo, path)
    r = requests.get(url)
    sha = r.json()[0]['sha']

    # link to history
    link = 'https://github.com/{}/commits/master/{}'.format(repo, path)

    return {'content': content, 'sha': sha, 'link': link, 'is_signed': False}

@app.route('/', methods=['POST', 'GET'])
def sign():
    # TODO: authenticate user with github oauth (no scope)
    # .form-control-static
    # TODO: add error at top if form didn't validate
    form = RegistrationForm(request.form)
    if request.method == 'POST' and form.validate():
        # check for existance of signatory (belt and braces)
        if Signatory.query.filter_by(username=session['username']).first():
            return '', 409
        sign = Signatory(
            username = session['username'],
            full_name = form.full_name.data,
            email = form.email.data,
            address = form.address.data.replace('\r', ''), # defaults to crlf?!
            telephone = form.telephone.data,
            version = form.cla_version.data
        )
        db.session.add(sign)
        db.session.commit()
        flash('Thanks for signing the CLA')
        # TODO: when someone signs the CLA, re-check all open pull requests
        # GET /repos/:owner/:repo/pulls?state=open
        # GET /repos/:owner/:repo/pulls/:number/commits
        # TODO: redirect to thank you page, then origin url (i.e. pull request)
        # clear session
        session.clear()
        return redirect(url_for('sign'))

    cla = get_cla_and_version()
    form.redirect = url_for('sign') + '#sign'

    # authenticated?
    if 'access_token' in session:
        # get username from github api
        url = 'https://api.github.com/user?access_token={}'
        r = requests.get(url.format(session['access_token']))
        try:
            login = r.json()['login']
        except AttributeError:
            app.logger.debug('error getting username from github, whoops')
        # check login against db
        if Signatory.query.filter_by(username=login).first():
            cla['is_signed'] = True
        session['username'] = login
        form.username = login

    return render_template('register.html', form=form, cla=cla)

@app.route('/_auth')
def auth():
    if 'code' in request.args:
        url = 'https://github.com/login/oauth/access_token'
        payload = {
            'client_id': environ.get('CLAM_GITHUB_CLIENT_ID'),
            'client_secret': environ.get('CLAM_GITHUB_CLIENT_SECRET'),
            'code': request.args['code']
        }
        #app.logger.debug(payload)
        headers = {'Accept': 'application/json'}
        r = requests.post(url, params=payload, headers=headers)
        answer = r.json()
        #app.logger.debug(answer)
        # get access_token from params
        # store username in session
        if 'access_token' in answer:
            session['access_token'] = r.json()['access_token']
        else:
            app.logger.error('github didn\'t return an access token, oh dear')
        return redirect(url_for('sign') + '#sign')
    url = 'https://github.com/login/oauth/authorize?client_id={}&scope=(no scope)'
    url = url.format(environ.get('CLAM_GITHUB_CLIENT_ID'))
    return redirect(url)

@app.route('/download', methods=['GET'])
def signatories():
    data = [s.to_json() for s in Signatory.query.all()]
    r = make_response(json.dumps(data, indent=2, sort_keys=True))
    r.mimetype = 'application/json'
    session.clear()
    return r

if __name__ == '__main__':
    import os
    if not os.path.exists('db.sqlite'):
        db.create_all()
    app.run(debug=True)
