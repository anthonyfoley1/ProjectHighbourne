// Click ratio name in RV summary table → update hidden RadioItems
document.addEventListener('click', function(e) {
    var el = e.target;
    // Check if clicked element is a ratio name (has rv-select- id)
    if (el.id && el.id.startsWith('rv-select-')) {
        var ratio = el.id.replace('rv-select-', '').replace(/-/g, '/');
        // Find the hidden ratio-dropdown RadioItems and update its value
        var radioInputs = document.querySelectorAll('#ratio-dropdown input[type="radio"]');
        radioInputs.forEach(function(input) {
            if (input.value === ratio) {
                input.click();
            }
        });
        // Visual feedback — highlight the clicked row
        document.querySelectorAll('[id^="rv-select-"]').forEach(function(span) {
            span.style.color = '#00bcd4';
            span.style.fontWeight = 'bold';
        });
        el.style.color = '#ff8c00';
    }
});
