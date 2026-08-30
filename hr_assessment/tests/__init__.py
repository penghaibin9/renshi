"""HR12 test package.

Keep this module free of imported ``TestCase`` classes.  Django treats an
explicit ``hr_assessment.tests`` label as a package only when discovery owns
the imports; re-exporting one class here made that common command silently run
only the ten import smoke tests instead of the complete HR12 suite.
"""
