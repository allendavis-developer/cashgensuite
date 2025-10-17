# Generated manually for Django 5.2.7

import django.db.models.deletion
from django.db import migrations, models


def set_default_item_model(apps, schema_editor):
    ItemModelAttributeValue = apps.get_model('pricing', 'ItemModelAttributeValue')
    ItemModel = apps.get_model('pricing', 'ItemModel')
    default_model = ItemModel.objects.first()
    for av in ItemModelAttributeValue.objects.all():
        av.item_model = default_model
        av.save()


class Migration(migrations.Migration):

    dependencies = [
        ('pricing', '0007_remove_marketitem_attributes_and_more'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='MarketItemAttributeValue',
            new_name='ItemModelAttributeValue',
        ),
        migrations.AddField(
            model_name='itemmodelattributevalue',
            name='item_model',
            field=models.ForeignKey(
                to='pricing.ItemModel',
                on_delete=django.db.models.deletion.CASCADE,
                related_name='attribute_values',
                null=True,  # make nullable initially
            ),
        ),
        migrations.RunPython(set_default_item_model),
        migrations.AlterField(
            model_name='itemmodelattributevalue',
            name='item_model',
            field=models.ForeignKey(
                to='pricing.ItemModel',
                on_delete=django.db.models.deletion.CASCADE,
                related_name='attribute_values',
                null=False,  # now make non-nullable
            ),
        ),
        migrations.AlterUniqueTogether(
            name='itemmodelattributevalue',
            unique_together={('item_model', 'attribute')},
        ),
        migrations.RemoveField(
            model_name='itemmodelattributevalue',
            name='market_item',
        ),
        migrations.RemoveField(
            model_name='marketitem',
            name='manufacturer',
        ),
        migrations.RemoveField(
            model_name='marketitem',
            name='model',
        ),
        migrations.AddField(
            model_name='marketitem',
            name='item_model',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='market_items',
                to='pricing.itemmodel'
            ),
        ),
    ]
