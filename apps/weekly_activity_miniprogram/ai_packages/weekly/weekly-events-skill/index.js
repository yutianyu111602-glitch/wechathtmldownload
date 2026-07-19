const searchEvents = require("./apis/searchEvents");

function registerSkill() {
  if (typeof wx === "undefined" || !wx.modelContext || !wx.modelContext.createSkill) return null;
  const skillPath = "ai_packages/weekly/weekly-events-skill";
  const skill = wx.modelContext.createSkill(skillPath);
  skill.registerAPI("searchEvents", searchEvents);
  return skill;
}

registerSkill();

module.exports = {
  registerSkill,
  searchEvents,
};
