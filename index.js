const express = require("express");
const cors = require("cors");
const app = express();
const api = require("./api");
const path = require('path');

app.use(express.static(path.join(__dirname, 'html')));
app.use(cors());
app.use(express.json());
app.set("json spaces", 2);

app.use(api);

app.listen(process.env.PORT || 3000, () => {
  console.log("OK");
});

module.exports = app;
