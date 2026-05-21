const path = require("path");
const fs = require("fs");
const { promisify } = require("util");

import("./dynamic-module").then((m) => m.run());

module.exports = { path, fs, promisify };
