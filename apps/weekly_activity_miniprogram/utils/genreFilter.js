// utils/genreFilter.js
// Compatibility adapter for callers that still need genre labels. Membership is
// owned by electronicRelevance so the mini-program cannot apply a second,
// different filter after the backend has produced the current projection.

var relevance = require("./electronicRelevance");

var ELECTRONIC = relevance.ELECTRONIC_RELEVANCE_HINTS;
var NON_ELECTRONIC = relevance.NON_ELECTRONIC_RELEVANCE_HINTS;

function genreOf(stylesList, textBlob) {
  return relevance.classifyElectronicMusicRelevance({
    genres: Array.isArray(stylesList) ? stylesList : [],
    title: textBlob || "",
  });
}

function itemGenreOf(item) {
  return relevance.classifyElectronicMusicRelevance(item);
}

function filterItemsByElectronic(items) {
  var source = Array.isArray(items) ? items : [];
  return source.filter(relevance.isElectronicMusicRelevantItem);
}

module.exports = {
  ELECTRONIC: ELECTRONIC,
  NON_ELECTRONIC: NON_ELECTRONIC,
  genreOf: genreOf,
  itemGenreOf: itemGenreOf,
  filterItemsByElectronic: filterItemsByElectronic,
};
