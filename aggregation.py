from drain.step import Step
from drain.aggregate import Aggregator
from drain import util

from itertools import product
import pandas as pd
import yaml

class AggregationBase(Step):
    """
    AggregationBase uses aggregate.Aggregator to aggregate data. It can include aggregations over multiple indexes and multiple data transformations (e.g. subsets). The combinations can be run in parallel and can be returned disjointl or concatenated. Finally the results may be pivoted and joined to other datasets.
    """
    def __init__(self, inputs, parallel=False, concat=True, target=False, prefix='', insert_args=None, **kwargs):
        """
        insert_args is a collection of argument names to insert into the results
        argument names that are not in insert_args will get pivoted
        block_args will run together when parallel=True
        """

        Step.__init__(self, inputs=inputs, parallel=parallel, 
                concat=concat, target=target, prefix=prefix, 
                insert_args=insert_args, **kwargs)

        if insert_args is None: self.insert_args = []

        if parallel:
            self.inputs = []
            # create a new Aggregation according to parallel_kwargs
            # pass our input to those steps
            # those become the inputs to this step
            for kwargs in self.parallel_kwargs:
                a = self.__class__(inputs=inputs, parallel=False, concat=concat,
                        target=target, insert_args=insert_args, prefix=prefix, **kwargs)
                self.inputs.append(a)
    
    @property
    def arguments(self):
        """
        arguments is a list of dictionaries of argument names and values.
        it must include the special 'index' argument, whose values are keys to plug into the self.indexes dictionary, whose values are the actual index
        the index is used for aggregation its index name is used to prefix the results
        """
        raise NotImplementedError

    def parallel_kwargs(self):
        """
        called by __init__ when parallel=True
        to get keyword args to pass to parallelized inputs
        """
        raise NotImplementedError

    def run(self,*args, **kwargs):
        if self.parallel:
            if self.concat:
                return kwargs
            else:
                return args

        if not self.parallel:
            dfs = []

            for argument in self.arguments:
                aggregator = self.get_aggregator(**argument)
                df = aggregator.aggregate(self.indexes[argument['index']])
                # insert insert_args
                for k in argument:
                    if k in self.insert_args:
                        df[k] = argument[k]
                dfs.append(df)

            if self.concat:
                to_concat = {}
                for argument, df in zip(self.arguments, dfs):
                    name = argument['index']
                    if name not in to_concat:
                        to_concat[name] = [df]
                    else:
                        to_concat[name].append(df)
                dfs = {name:pd.concat(dfs) for name,dfs in to_concat.iteritems()}

        return dfs

    def get_aggregator(self, **kwargs):
        """
        Given the arguments, return an aggregator

        This method exists to allow subclasses to use Aggregator objects efficiently, i.e. only apply AggregateSeries once per set of Aggregates. If the set of Aggregates depends on some or none of the arguments the subclass need not recreate Aggregators
        """
        raise NotImplementedError


class SimpleAggregation(AggregationBase):
    """
    A simple AggreationBase subclass with a single aggregrator
    The only argument is the index
    An implementation need only define an aggregates attributes
    """
    def __init__(self, inputs, indexes, **kwargs):
        AggregationBase.__init__(self, inputs=inputs, indexes=indexes, **kwargs)

        # if indexes was not a dict but a list, make it a dict
        if not isinstance(indexes, dict):
            self.indexes = {index:index for index in indexes}

    @property
    def arguments(self):
        return [{'index':name} for name in self.indexes]

    def get_aggregator(self, **kwargs):
        return self.aggregator

    @property
    def aggregator(self):
        return Aggregator(self.inputs[0].get_result(), self.aggregates)

    @property
    def parallel_kwargs(self):
        """
        parallize by sending each index to a different step
        """
        return [{'indexes': [index]} for index in self.indexes]


class SpacetimeAggregation(AggregationBase):
    """
    SpacetimeAggregation is an Aggregation over space and time.
    Specifically, the index is a spatial index and an additional date and delta argument select a subset of the data to aggregate.
    We assume that the index and deltas are independent of the date, so every date is aggregated to all spacedeltas
    The aggregates can depend on any of these three arguments.
    """
    def __init__(self, spacedeltas, dates, date_column, censor_columns, **kwargs):
        """
        spacedeltas is a dict of the form {name: (index, deltas)} where deltas is an array of delta strings
        dates are end dates for the aggregators
        """
        AggregationBase.__init__(self, spacedeltas=spacedeltas, 
                dates=dates, date_column=date_column, censor_columns=censor_columns, **kwargs)

    @property
    def indexes(self):
        return [{name:value[0]} for name,value in self.spacedeltas.iteritems()]

    @property
    def arguments(self):
        a = []
        for date in self.dates:
            for name,spacedelta in self.spacedeltas.iteritems():
                for delta in spacedeltas[1]:
                    a.append({'date':date, 'delta': delta, 'index':name})

        return a

    @property
    def parallel_kwargs(self):
        return [{'spacedeltas':self.spacedeltas, 'dates':[date]} for date in self.dates]
