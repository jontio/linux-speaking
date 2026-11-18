// The key this computer's engine and this add-on prove to each other that they hold.
//
// There is none here. scripts/build-xpi.sh, which the installer runs, makes one for the
// computer it is run on and writes it into the add-on's file in place of this. So an
// add-on file is for one computer and is not for passing on. Without a key the add-on
// does nothing.
"use strict";

const LINUX_SPEAKING_KEY = "";
