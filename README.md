```
$ git clone https://github.com/mcneel/clam.git
$ cd clam
```

Running locally
```
foreman run python clam.py
```

Heroku...
```
$ heroku create clam-example-57
$ heroku addons:create heroku-postgresql
$ heroku config:set CLAM_GITHUB_ORG=mcneel
$ heroku config:set CLAM_BASEURL=https://mcneel-cla.herokuapp.com
$ heroku config:set CLAM_GITHUB_TOKEN=your_github_access_token_with_repo_scope
```

Webhook: `https://mcneel-cla.herokuapp.com/_github`
```
curl -d @pull.json -H "Content-Type: application/json" -X POST localhost:5000/_github
```
