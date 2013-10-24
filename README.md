This script migrates issues from Trac to Github:

* Component & Issue-Type are converted to labels
* Comments to issues are copied over
* Basic conversion of Wiki Syntax in comments and descriptions
* All titles will be suffixed with `(Trac #<>)` for ease of searching
* All created issues will have the full Trac attributes appended to the issue body in JSON format
* Issue links (i.e. `#1`, `refs 1`, etc.) will be converted to use the corresponding Github issue number instead of the original Trac ticket ID

Run migrate.py with --help for more information
