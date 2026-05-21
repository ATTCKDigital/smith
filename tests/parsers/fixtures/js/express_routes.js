const express = require("express");
const app = express();
const router = express.Router();

app.get("/", function rootHandler(req, res) {
  res.send("hello");
});

app.post("/items", (req, res) => {
  res.json({ ok: true });
});

router.put("/users/:id", updateUser);
router.delete("/users/:id", deleteUser);

function updateUser(req, res) {
  res.json({});
}

function deleteUser(req, res) {
  res.status(204).end();
}

module.exports = { app, router };
