var nodeHistoryPlots;

function getNodeHistoryPlotStore() {
  if (!nodeHistoryPlots) {
    nodeHistoryPlots = {};
  }
  return nodeHistoryPlots;
}

function getNodeHistoryMaxPoints() {
  return 16;
}

function getNodeHistoryChartHeight() {
  return 240;
}

function getNodeHistoryPlotWidth(plotRoot) {
  return Math.max(plotRoot ? plotRoot.clientWidth : 0, 280);
}

function getHistoryRecordTimestamp(historyRecord) {
  if (!historyRecord || historyRecord.recorded_at === null || historyRecord.recorded_at === undefined) {
    return null;
  }
  var timestamp = Number(historyRecord.recorded_at);
  return isNaN(timestamp) ? null : timestamp;
}

function getNodeHistoryTimeMode(spanSeconds) {
  if (spanSeconds >= 3 * 3600) {
    return 'hours';
  }
  if (spanSeconds >= 3 * 60) {
    return 'minutes';
  }
  return 'seconds';
}

function formatNodeHistoryRelativeTick(timestampSeconds, latestTimestampSeconds, timeMode) {
  var deltaSeconds = Math.max(0, Math.round(Number(latestTimestampSeconds) - Number(timestampSeconds)));

  if (deltaSeconds === 0) {
    return 'now';
  }

  if (timeMode === 'hours') {
    return '-' + (deltaSeconds / 3600).toFixed(deltaSeconds >= 10 * 3600 ? 0 : 1) + 'h';
  }

  if (timeMode === 'minutes') {
    return '-' + Math.round(deltaSeconds / 60) + 'm';
  }

  return '-' + deltaSeconds + 's';
}

function describeNodeHistorySpan(spanSeconds, timeMode) {
  if (timeMode === 'hours') {
    return (spanSeconds / 3600).toFixed(spanSeconds >= 10 * 3600 ? 0 : 1) + ' hours';
  }
  if (timeMode === 'minutes') {
    return Math.max(1, Math.round(spanSeconds / 60)) + ' minutes';
  }
  return Math.max(1, Math.round(spanSeconds)) + ' seconds';
}

function sampleNodeHistoryRecords(rawHistory) {
  var maxPoints = getNodeHistoryMaxPoints();
  var sampledHistory = [];
  var usedIndexes = {};
  var index;
  var cursor;

  if (rawHistory.length <= maxPoints) {
    return rawHistory.slice();
  }

  for (cursor = 0; cursor < maxPoints; cursor += 1) {
    index = Math.round((cursor * (rawHistory.length - 1)) / (maxPoints - 1));
    if (!usedIndexes[index]) {
      sampledHistory.push(rawHistory[index]);
      usedIndexes[index] = true;
    }
  }

  if (!usedIndexes[rawHistory.length - 1]) {
    sampledHistory.push(rawHistory[rawHistory.length - 1]);
  }

  return sampledHistory;
}

function getNodeHistoryMetricMeta(metricKey) {
  if (metricKey === 'cpu') {
    return {
      axisLabel: 'CPU',
      color: '#4fd1c5',
      emptyMessage: 'CPU history will appear once the monitor has enough healthy samples.',
      formatAxisValue: function(value) {
        return Math.round(value) + '%';
      },
      formatLatestValue: function(value) {
        return Number(value).toFixed(1) + '%';
      },
      getValue: function(historyRecord) {
        if (historyRecord.cpu_usage_pct === null || historyRecord.cpu_usage_pct === undefined) {
          return null;
        }
        return Number(historyRecord.cpu_usage_pct);
      },
      getYRange: function() {
        return [0, 100];
      },
      title: 'CPU usage history',
    };
  }

  if (metricKey === 'vram') {
    return {
      axisLabel: 'VRAM',
      color: '#82aaff',
      emptyMessage: 'VRAM history will appear once GPU telemetry has been collected.',
      formatAxisValue: function(value) {
        return Math.round(value) + '%';
      },
      formatLatestValue: function(value, historyRecord) {
        if (
          historyRecord &&
          historyRecord.gpu_memory_used_bytes !== null &&
          historyRecord.gpu_memory_used_bytes !== undefined &&
          historyRecord.gpu_memory_total_bytes
        ) {
          return bytesToGiB(historyRecord.gpu_memory_used_bytes) + ' / ' + bytesToGiB(historyRecord.gpu_memory_total_bytes);
        }
        return Number(value).toFixed(1) + '%';
      },
      getValue: function(historyRecord) {
        if (
          historyRecord.gpu_memory_used_bytes === null ||
          historyRecord.gpu_memory_used_bytes === undefined ||
          historyRecord.gpu_memory_total_bytes === null ||
          historyRecord.gpu_memory_total_bytes === undefined ||
          Number(historyRecord.gpu_memory_total_bytes) <= 0
        ) {
          return null;
        }
        return (Number(historyRecord.gpu_memory_used_bytes) / Number(historyRecord.gpu_memory_total_bytes)) * 100;
      },
      getYRange: function() {
        return [0, 100];
      },
      title: 'VRAM usage history',
    };
  }

  if (metricKey === 'assigned') {
    return {
      axisLabel: 'Assigned',
      color: '#f6c445',
      emptyMessage: 'Assignment history will appear once the node has been sampled.',
      formatAxisValue: function(value) {
        return String(Math.round(value));
      },
      formatLatestValue: function(value) {
        var roundedValue = Math.round(value);
        return roundedValue + ' ' + (roundedValue === 1 ? 'person' : 'people');
      },
      getValue: function(historyRecord) {
        if (historyRecord.assigned_user_count === null || historyRecord.assigned_user_count === undefined) {
          return null;
        }
        return Number(historyRecord.assigned_user_count);
      },
      getYRange: function(values) {
        var maxValue = 0;
        values.forEach(function(value) {
          if (value !== null && value > maxValue) {
            maxValue = value;
          }
        });
        return [0, Math.max(2, Math.ceil(maxValue) + 1)];
      },
      title: 'People assigned history',
    };
  }

  return {
    axisLabel: 'Fitness',
    color: '#ff8d3f',
    emptyMessage: 'Fitness history will appear once enough healthy samples have been collected.',
    formatAxisValue: function(value) {
      return Math.round(value) + '%';
    },
    formatLatestValue: function(value) {
      return Number(value).toFixed(1) + '%';
    },
    getValue: function(historyRecord) {
      if (historyRecord.fitness_score === null || historyRecord.fitness_score === undefined) {
        return null;
      }
      return Number(historyRecord.fitness_score);
    },
    getYRange: function() {
      return [0, 100];
    },
    title: 'Fitness history',
  };
}

function buildNodeHistoryPlotModel(instanceId, metricKey) {
  var rawHistory = Array.isArray(nodeHealthHistory[instanceId]) ? nodeHealthHistory[instanceId] : [];
  var metricMeta = getNodeHistoryMetricMeta(metricKey);
  var sampledHistory = sampleNodeHistoryRecords(rawHistory);
  var timestamps = [];
  var values = [];
  var latestTimestamp = null;
  var latestUsableRecord = null;
  var latestUsableValue = null;

  sampledHistory.forEach(function(historyRecord) {
    var timestamp = getHistoryRecordTimestamp(historyRecord);
    var value;
    if (timestamp === null) {
      return;
    }

    value = metricMeta.getValue(historyRecord);
    timestamps.push(timestamp);
    values.push(value);

    latestTimestamp = timestamp;
    if (value !== null) {
      latestUsableRecord = historyRecord;
      latestUsableValue = value;
    }
  });

  return {
    latestTimestamp: latestTimestamp,
    latestUsableRecord: latestUsableRecord,
    latestUsableValue: latestUsableValue,
    metricMeta: metricMeta,
    rawCount: rawHistory.length,
    sampledCount: timestamps.length,
    timestamps: timestamps,
    values: values,
  };
}

function setNodeHistorySummary(panel, summaryText) {
  var summaryNode = panel.querySelector('.node-history-summary');
  if (summaryNode) {
    summaryNode.textContent = summaryText;
  }
}

function destroyNodeHistoryPlot(instanceId) {
  var plotStore = getNodeHistoryPlotStore();
  if (plotStore[instanceId]) {
    plotStore[instanceId].destroy();
    delete plotStore[instanceId];
  }
}

function destroyNodeHistoryPlots() {
  var plotStore = getNodeHistoryPlotStore();

  Object.keys(plotStore).forEach(function(instanceId) {
    plotStore[instanceId].destroy();
  });

  nodeHistoryPlots = {};
}

function renderEmptyNodeHistoryPanel(panel, message, summaryText) {
  var instanceId = panel.getAttribute('data-instance-id');
  var plotRoot = panel.querySelector('.node-history-plot');
  destroyNodeHistoryPlot(instanceId);

  if (plotRoot) {
    plotRoot.innerHTML = '<div class="health-empty">' + escapeHtml(message) + '</div>';
  }
  setNodeHistorySummary(panel, summaryText);
}

function buildNodeHistorySummary(plotModel, timeMode, spanSeconds) {
  var metricMeta = plotModel.metricMeta;
  var latestValueText;

  if (plotModel.latestUsableValue === null || plotModel.latestUsableValue === undefined) {
    return 'Showing ' + plotModel.sampledCount + ' sampled points across ' + describeNodeHistorySpan(spanSeconds, timeMode) + '. The selected metric has no valid values yet.';
  }

  latestValueText = metricMeta.formatLatestValue(plotModel.latestUsableValue, plotModel.latestUsableRecord);
  return 'Showing ' + plotModel.sampledCount + ' sampled points from ' + plotModel.rawCount + ' retained entries across ' + describeNodeHistorySpan(spanSeconds, timeMode) + '. Latest available value: ' + latestValueText + '.';
}

function renderNodeHistoryPanel(panel) {
  var instanceId = panel.getAttribute('data-instance-id');
  var plotRoot = panel.querySelector('.node-history-plot');
  var metricSelect = panel.querySelector('.node-history-select');
  var metricKey = metricSelect ? metricSelect.value : getSelectedHistoryMetric(instanceId);
  var plotModel;
  var spanSeconds;
  var timeMode;

  if (!plotRoot) {
    return;
  }

  if (typeof uPlot === 'undefined') {
    renderEmptyNodeHistoryPanel(
      panel,
      'The charting library did not load.',
      'Node history plotting is unavailable because the bundled graphing library is missing.'
    );
    return;
  }

  plotModel = buildNodeHistoryPlotModel(instanceId, metricKey);
  if (plotModel.timestamps.length === 0) {
    renderEmptyNodeHistoryPanel(
      panel,
      'History will appear once the monitor collects samples for this node.',
      'The node monitor has not yet retained any historical samples for this node.'
    );
    return;
  }

  if (plotModel.latestUsableValue === null && metricKey !== 'assigned') {
    renderEmptyNodeHistoryPanel(
      panel,
      plotModel.metricMeta.emptyMessage,
      'The history exists, but this metric does not have a valid value in the retained samples yet.'
    );
    return;
  }

  destroyNodeHistoryPlot(instanceId);
  plotRoot.innerHTML = '';

  spanSeconds = Math.max(0, Number(plotModel.timestamps[plotModel.timestamps.length - 1]) - Number(plotModel.timestamps[0]));
  timeMode = getNodeHistoryTimeMode(spanSeconds);

  getNodeHistoryPlotStore()[instanceId] = new uPlot(
    {
      width: getNodeHistoryPlotWidth(plotRoot),
      height: getNodeHistoryChartHeight(),
      legend: { show: false },
      cursor: { drag: { x: true, y: false } },
      scales: {
        x: { time: false },
        y: { auto: false, range: plotModel.metricMeta.getYRange(plotModel.values) },
      },
      axes: [
        {
          stroke: '#8d97a6',
          grid: { stroke: 'rgba(255, 255, 255, 0.06)' },
          values: function(u, values) {
            return values.map(function(value) {
              return formatNodeHistoryRelativeTick(value, plotModel.latestTimestamp, timeMode);
            });
          },
        },
        {
          stroke: '#8d97a6',
          size: 60,
          grid: { stroke: 'rgba(255, 255, 255, 0.06)' },
          values: function(u, values) {
            return values.map(function(value) {
              return plotModel.metricMeta.formatAxisValue(value);
            });
          },
        },
      ],
      series: [
        {},
        {
          label: plotModel.metricMeta.title,
          stroke: plotModel.metricMeta.color,
          width: 2,
          points: { show: false },
          spanGaps: false,
        },
      ],
    },
    [plotModel.timestamps, plotModel.values],
    plotRoot
  );

  setNodeHistorySummary(panel, buildNodeHistorySummary(plotModel, timeMode, spanSeconds));
}

function resizeNodeHistoryPlots() {
  var plotStore = getNodeHistoryPlotStore();

  Object.keys(plotStore).forEach(function(instanceId) {
    var panel = document.querySelector('.node-history-panel[data-instance-id="' + instanceId.replace(/"/g, '\\"') + '"]');
    var plotRoot;
    if (!panel) {
      destroyNodeHistoryPlot(instanceId);
      return;
    }

    plotRoot = panel.querySelector('.node-history-plot');
    if (!plotRoot) {
      return;
    }

    plotStore[instanceId].setSize({
      width: getNodeHistoryPlotWidth(plotRoot),
      height: getNodeHistoryChartHeight(),
    });
  });
}

window.addEventListener('resize', resizeNodeHistoryPlots);
