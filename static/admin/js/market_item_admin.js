(function($) {
    'use strict';
    
    $(document).ready(function() {
        var categoryField = $('#id_category');
        var manufacturerField = $('#id_manufacturer');
        var modelField = $('#id_model');
        
        function updateModelChoices() {
            var categoryId = categoryField.val();
            var manufacturerId = manufacturerField.val();
            
            if (!categoryId) {
                modelField.empty().append('<option value="">---------</option>');
                modelField.prop('disabled', true);
                return;
            }
            
            // Build URL with filters
            var url = '/admin/get-models/?category=' + categoryId;
            if (manufacturerId) {
                url += '&manufacturer=' + manufacturerId;
            }
            
            $.ajax({
                url: url,
                success: function(data) {
                    var currentValue = modelField.val();
                    modelField.empty();
                    modelField.append('<option value="">---------</option>');
                    
                    $.each(data.models, function(index, model) {
                        var option = $('<option></option>')
                            .attr('value', model.id)
                            .text(model.name);
                        
                        if (model.id == currentValue) {
                            option.attr('selected', 'selected');
                        }
                        
                        modelField.append(option);
                    });
                    
                    modelField.prop('disabled', false);
                }
            });
        }
        
        // Update models when category or manufacturer changes
        categoryField.on('change', function() {
            updateModelChoices();
        });
        
        manufacturerField.on('change', function() {
            updateModelChoices();
        });
        
        // Initialize on page load if category is already set
        if (categoryField.val()) {
            updateModelChoices();
        }
    });
})(django.jQuery);