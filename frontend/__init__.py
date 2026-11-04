"""
MODULE NAME
-----------
FRONTEND PACKAGE

PURPOSE
-------
Provide the presentation-layer integration modules used by
the Gradio frontend to communicate with FastAPI.

ENVIRONMENT / CONFIGURATION
---------------------------
Frontend API configuration is managed by individual modules.

DEPENDENCIES
------------
Python standard library and existing project dependencies.

RESPONSIBILITIES / WHAT WE TEST
-------------------------------
Organize frontend API communication and session management
without duplicating backend business logic.

SECURITY NOTES
--------------
Authentication and authorization remain enforced by FastAPI.
Frontend modules must not use global mutable user credentials.
"""