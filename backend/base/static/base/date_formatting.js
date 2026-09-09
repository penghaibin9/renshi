/* Display-only: formats belong to this authorised document, never localStorage. */
var DateFormattingUtility = DateFormattingUtility || class DateFormattingUtility {
    constructor() {
        this.dateFormat = 'MMM. D, YYYY';
        try {
            const formats = JSON.parse(document.getElementById('account-display-formats')?.textContent || '{}');
            if (typeof formats.dateFormat === 'string' && formats.dateFormat) this.dateFormat = formats.dateFormat;
        } catch (_) { /* Missing/malformed display projection retains the non-school default. */ }
    }

    setDateFormat(format) {
        // Page-local preview only. The existing settings POST owns persistence;
        // a reload (including after an error) reads the actual school setting.
        if (typeof format === 'string' && format) this.dateFormat = format;
    }

    getFormattedDate(date) {
        const format = this.dateFormat;
        let processedDate = date;
        if (typeof date === 'string') {
            if (format === 'DD-MM-YYYY') {
                processedDate = date.replace(/(\d{2})-(\d{2})-(\d{4})/, '$3-$2-$1');
            } else if (format === 'DD.MM.YYYY') {
                processedDate = date.replace(/(\d{2})\.(\d{2})\.(\d{4})/, '$3-$2-$1');
            } else if (format === 'DD/MM/YYYY') {
                processedDate = date.replace(/(\d{2})\/(\d{2})\/(\d{4})/, '$3-$2-$1');
            }
        }
        return moment(processedDate).format(format);
    }
};
var dateFormatter = dateFormatter || new DateFormattingUtility();
