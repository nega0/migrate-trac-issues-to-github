This script migrates issues from Trac to Github:

* Component & Issue-Type are converted to labels
* Comments to issues are copied over
* Basic conversion of Wiki Syntax in comments and descriptions
* All titles will be suffixed with `(Trac #<>)` for ease of searching
* All created issues will have the full Trac attributes appended to the issue body in JSON format



Run migrate.py with --help for more information