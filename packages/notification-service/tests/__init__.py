"""
packages/notification-service/tests/__init__.py

FILE HEADER
-----------
Business problem this file solves:
    Marks the tests directory as a Python package so pytest can discover and import
    test_channels.py and test_router.py as `notification_service.tests` siblings.

Where it sits in the flow:
    Test package init for packages/notification-service/tests/.

What calls it / what it calls:
    Called by: pytest during collection.
    Calls: nothing.

What breaks if removed:
    pytest may still discover tests via rootdir, but package-relative imports are cleaner with
    this present.

Language conventions:
    Python 3.11+. Keep empty/minimal.
"""
