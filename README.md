# Migrate Trac tickets to GitHub Issues

This script migrates issues from Trac to GitHub:

* Component & Issue-Type are converted to labels
* Comments to issues are copied over
* Basic conversion of Wiki Syntax in comments and descriptions
* All titles will be suffixed with `(Trac #<>)` for ease of searching
* All created issues will have the full Trac attributes appended to the issue body in JSON format
* Issue links (i.e. `#1`, `refs 1`, etc.) will be converted to use the corresponding Github issue number instead of the original Trac ticket ID

## Requirements

 * Python 2.7
 * Trac with the [XmlRpcPlugin](https://trac-hacks.org/wiki/XmlRpcPlugin)
 * [PyGithub](https://pypi.python.org/pypi/PyGithub)
  ```
  pip install -r requirements.txt
  ```

## How
```
./migrate.py --trac-url=https://trac.example.org --github-project=YOUR_USER/YOUR_PROJECT
```

## Details

* You will be prompted for the username and password needed to access Trac, and GitHub password if needed. If your gitconfig has a section with github.token, or github.user and github.password, those values will automatically be used. It is recommended that you use a token (see https://github.com/settings/applications) instead of saving a real password:
```
  git config --local github.token TOKEN_VALUE
```

* You may use the --username-map option to specify a text file containing tab-separated lines with Trac username and equivalent GitHub username pairs. It is likely that you would not want to include usernames for people who are no longer working on your project as they may receive assignment notifications for old tickets. The GitHub API does not provide any way to suppress notifications.

Run migrate.py with `--help` for more information

```
usage: migrate.py [-h] --trac-url TRAC_URL --github-project GITHUB_PROJECT
                  [--github-token GITHUB_TOKEN]
                  [--github-username GITHUB_USERNAME]
                  [--github-api-url GITHUB_API_URL]
                  [--github-project GITHUB_PROJECT]
                  [--username-map USERNAME_MAP]

optional arguments:
  -h, --help            show this help message and exit
  --trac-username TRAC_USERNAME
                        Trac username (default: caktux)
  --trac-url TRAC_URL   Trac base URL (`USERNAME` and `PASSWORD` will be
                        expanded)
  --github-token GITHUB_TOKEN
                        GitHub token (default: ...)
  --github-username GITHUB_USERNAME
                        GitHub username (default: caktux)
  --github-api-url GITHUB_API_URL
                        GitHub API URL (default: https://api.github.com)
  --github-project GITHUB_PROJECT
                        GitHub Project: e.g. username/project
  --username-map USERNAME_MAP
                        File containing tab-separated Trac:GitHub username
                        mappings
```

## License

 License: http://www.wtfpl.net/
