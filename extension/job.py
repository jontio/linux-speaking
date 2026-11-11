"""Starts the dictation server when LibreOffice starts."""
import unohelper
from com.sun.star.task import XJob

import ls_server


class Job(unohelper.Base, XJob):
    def __init__(self, ctx):
        self.ctx = ctx

    def execute(self, args):
        ls_server.start(self.ctx)
        return None


g_ImplementationHelper = unohelper.ImplementationHelper()
g_ImplementationHelper.addImplementation(
    Job, "io.github.jontio.linuxspeaking.Job", ("com.sun.star.task.Job",)
)
