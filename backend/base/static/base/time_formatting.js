/* Display-only: no management API reads or cross-school browser preference. */
var TimeFormattingUtility = TimeFormattingUtility || class TimeFormattingUtility {
    constructor() {
        this.timeFormat = 'hh:mm A';
        try {
            const formats = JSON.parse(document.getElementById('account-display-formats')?.textContent || '{}');
            if (typeof formats.timeFormat === 'string' && formats.timeFormat) this.timeFormat = formats.timeFormat;
        } catch (_) { /* Non-school default when the display projection is absent. */ }
    }

    setTimeFormat(format) {
        // Preserve the existing page-local settings preview, not persistence.
        if (typeof format === 'string' && format) this.timeFormat = format;
    }

    getFormattedTime(time) {
        return moment(time, 'hh:mm A').format(this.timeFormat);
    }

    getFormattedTime12Hour(time) {
        return this.getFormattedTime(time).replace(/^(\d{1,2}:\d{2}):\d{2}$/, '$1');
    }
};
var timeFormatter = timeFormatter || new TimeFormattingUtility();
