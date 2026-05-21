import fs from "fs";

function readConfig(path) {
  return fs.readFileSync(path, "utf8");
}

export default readConfig;
