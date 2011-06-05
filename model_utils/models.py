import warnings

from datetime import datetime

from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.utils.translation import ugettext_lazy as _
from django.db.models.fields import FieldDoesNotExist
from django.core.exceptions import ImproperlyConfigured

from .managers import manager_from, InheritanceCastMixin, \
    QueryManager
from .fields import AutoCreatedField, AutoLastModifiedField, \
    StatusField, MonitorField
from . import update

class InheritanceCastModel(models.Model):
    """
    An abstract base class that provides a ``real_type`` FK to ContentType.

    For use in trees of inherited models, to be able to downcast
    parent instances to their child types.

    Pending deprecation; use InheritanceManager instead.

    """
    real_type = models.ForeignKey(ContentType, editable=False, null=True)

    objects = manager_from(InheritanceCastMixin)

    def __init__(self, *args, **kwargs):
        warnings.warn(
            "InheritanceCastModel is pending deprecation. "
            "Use InheritanceManager instead.",
            PendingDeprecationWarning,
            stacklevel=2)
        super(InheritanceCastModel, self).__init__(*args, **kwargs)

    def save(self, *args, **kwargs):
        if not self.id:
            self.real_type = self._get_real_type()
        super(InheritanceCastModel, self).save(*args, **kwargs)

    def _get_real_type(self):
        return ContentType.objects.get_for_model(type(self))

    def cast(self):
        return self.real_type.get_object_for_this_type(pk=self.pk)

    class Meta:
        abstract = True


class TimeStampedModel(models.Model):
    """
    An abstract base class model that provides self-updating
    ``created`` and ``modified`` fields.

    """
    created = AutoCreatedField(_('created'))
    modified = AutoLastModifiedField(_('modified'))

    class Meta:
        abstract = True


class TimeFramedModel(models.Model):
    """
    An abstract base class model that provides ``start``
    and ``end`` fields to record a timeframe.

    """
    start = models.DateTimeField(_('start'), null=True, blank=True)
    end = models.DateTimeField(_('end'), null=True, blank=True)

    class Meta:
        abstract = True

class StatusModel(models.Model):
    """
    An abstract base class model with a ``status`` field that
    automatically uses a ``STATUS`` class attribute of choices, a
    ``status_changed`` date-time field that records when ``status``
    was last modified, and an automatically-added manager for each
    status that returns objects with that status only.

    """
    status = StatusField(_('status'))
    status_changed = MonitorField(_('status changed'), monitor='status')

    class Meta:
        abstract = True

def add_status_query_managers(sender, **kwargs):
    """
    Add a Querymanager for each status item dynamically.

    """
    if not issubclass(sender, StatusModel):
        return
    for value, name in getattr(sender, 'STATUS', ()):
        try:
            sender._meta.get_field(name)
            raise ImproperlyConfigured("StatusModel: Model '%s' has a field "
                                       "named '%s' which conflicts with a "
                                       "status of the same name."
                                       % (sender.__name__, name))
        except FieldDoesNotExist:
            pass
        sender.add_to_class(value, QueryManager(status=value))

def add_timeframed_query_manager(sender, **kwargs):
    """
    Add a QueryManager for a specific timeframe.

    """
    if not issubclass(sender, TimeFramedModel):
        return
    try:
        sender._meta.get_field('timeframed')
        raise ImproperlyConfigured("Model '%s' has a field named "
                                   "'timeframed' which conflicts with "
                                   "the TimeFramedModel manager." 
                                   % sender.__name__)
    except FieldDoesNotExist:
        pass
    sender.add_to_class('timeframed', QueryManager(
        (models.Q(start__lte=datetime.now) | models.Q(start__isnull=True)) &
        (models.Q(end__gte=datetime.now) | models.Q(end__isnull=True))
    ))


models.signals.class_prepared.connect(add_status_query_managers)
models.signals.class_prepared.connect(add_timeframed_query_manager)

class PositionedModelMixin(object):
    def get_position_field_name(self): return 'position'
    def get_position_filter_args(self):
        ''' Criteria which instances' positions are relative to.
            For example, if it's the cart item model,
            it could return {"cart": self.cart}.
        '''
        return {}
    def refresh_positions(self):
        "Update positions so that they increment by 1."
        counter = 1
        filter = self.get_position_filter_args()
        position_f = self.get_position_field_name()
        for obj in self.__class__.objects.filter(filter):
            update(obj, **{position_f: counter})
            counter += 1

    def get_next_free_position(self):
        self.refresh_positions() # Just in case
        filter = self.get_position_filter_args()
        position_f = self.get_position_field_name()
        max_position = self.__class__.objects.filter(filter)\
            .aggregate(Max(position_f))['%s_max' % position_f]
        if max_position: return max_position + 1
        else: return 1

    def move_to(self, position):
        ''' Exchanges positions between self and an object
            with given position.
            Returns False if no object with given position
            is found (nothing to swap places with).
        '''
        position = int(position)
        filter = self.get_position_filter_args()
        filter[position_f] = position
        position_f = self.get_position_field_name()
        try:
            # Find other variant with given new position
            other = self.__class__.objects.get(filter)
        except self.__class__.DoesNotExist:
            return False
        # Set temporary position to us
        update(self, **{position_f: 0})
        # Move other to our position
        update(other, **{position_f: getattr(self, position_f)})
        # Move us to other's position
        update(self, **{position_f: position})
        return position

    def move_up(self, times=1):
        return move_to(getattr(self, self.get_position_field_name()) - times)
    def move_down(self, times=1):
        return move_to(getattr(self, self.get_position_field_name()) + times)
