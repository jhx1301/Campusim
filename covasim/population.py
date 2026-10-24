'''
Defines functions for making the population.
'''

#%% Imports
import numpy as np # Needed for a few things not provided by pl
import sciris as sc
from . import requirements as cvreq
from . import utils as cvu
from . import misc as cvm
from . import base as cvb
from . import data as cvdata
from . import defaults as cvd
from . import parameters as cvpar
from . import people as cvppl


# Specify all externally visible functions this file defines
__all__ = ['make_people', 'make_randpop', 'make_random_contacts',
           'make_microstructured_contacts', 'make_hybrid_contacts',
           'make_campus_contacts', 'CampusClassroomLayer', 'CampusLabLayer', 'make_synthpop']



def make_people(sim, popdict=None, die=True, reset=False, recreate=False, verbose=None, **kwargs):
    '''
    Make the actual people for the simulation.

    Usually called via ``sim.initialize()``. While in theory this function can be
    called directly by the user, usually it's better to call ``cv.People()`` directly.

    Args:
        sim      (Sim)  : the simulation object; population parameters are taken from the sim object
        popdict  (any)  : if supplied, use this population dictionary instead of generating a new one; can be a dict, SynthPop, or People object
        die      (bool) : whether or not to fail if synthetic populations are requested but not available
        reset    (bool) : whether to force population creation even if self.popdict/self.people exists
        recreate (bool) : whether to recreate (re-instantiate) the People object even if already supplied
        verbose  (bool) : level of detail to print
        kwargs   (dict) : passed to make_randpop() or make_synthpop()

    Returns:
        people (People): people
    '''

    # Set inputs and defaults
    pop_size = int(sim['pop_size']) # Shorten
    pop_type = sim['pop_type'] # Shorten
    if verbose is None:
        verbose = sim['verbose']

    # Check which type of population to produce
    if pop_type == 'synthpops':
        if not cvreq.check_synthpops(): # pragma: no cover
            errormsg = f'You have requested "{pop_type}" population, but synthpops is not available; please use random, clustered, or hybrid'
            if die:
                raise ValueError(errormsg)
            else:
                print(errormsg)
                pop_type = 'hybrid'

        location = sim['location']
        if location and verbose: # pragma: no cover
            warnmsg = f'Not setting ages or contacts for "{location}" since synthpops contacts are pre-generated'
            cvm.warn(warnmsg)

    # If a people object or popdict is supplied, use it
    if sim.people and not reset:
        sim.people.initialize(sim_pars=sim.pars)
        return sim.people # If it's already there, just return
    elif sim.popdict and popdict is None:
        popdict = sim.popdict # Use stored one
        sim.popdict = None # Once loaded, remove

    # Handle SynthPops separately: run the popdict through the function even if it already exists
    if pop_type == 'synthpops':
        popdict = make_synthpop(sim, popdict=popdict, **kwargs)

    # Main use case: no popdict is supplied, so create one
    else:
        if popdict is None:
            if pop_type in ['random', 'hybrid', 'campus']:
                popdict = make_randpop(sim, microstructure=pop_type, **kwargs) # Main use case: create a random or hybrid population
            else: # pragma: no cover
                errormsg = f'Population type "{pop_type}" not found; choices are random, hybrid, synthpops or campus'
                raise ValueError(errormsg)

    # Ensure prognoses are set
    if sim['prognoses'] is None:
        sim['prognoses'] = cvpar.get_prognoses(sim['prog_by_age'], version=sim._default_ver)

    # Do minimal validation and create the people
    validate_popdict(popdict, sim.pars, verbose=verbose)
    if isinstance(popdict, cvppl.People) and not recreate:
        people = popdict
        people.set_pars(sim.pars)
    else:
        if 'role' not in popdict:
            popdict['role'] = np.full(sim['pop_size'], -1, dtype=cvd.default_int)
        if 'student_level' not in popdict:
            popdict['student_level'] = np.full(sim['pop_size'], 2, dtype=cvd.default_int)

        people = cvppl.People(
            sim.pars,
            uid=popdict['uid'],
            age=popdict['age'],
            sex=popdict['sex'],
            role=popdict['role'],
            student_level=popdict['student_level'],
            contacts=popdict['contacts'],
        )

    # Attach campus classroom dynamic layer and persistent class groups
    if pop_type == 'campus':
        people.class_groups_ug = popdict.get('class_groups_ug', [])
        people.class_groups_gr = popdict.get('class_groups_gr', [])
        people.lab_groups = popdict.get('lab_groups', [])
        people.campus_registry_metadata = popdict.get('campus_registry_metadata', {})

        people.contacts['clu'] = CampusClassroomLayer(
            people.contacts['clu'],
            class_groups=people.class_groups_ug,
            k_ts=sim.pars.get('campus_k_ts', 6.0),
            k_ss=sim.pars.get('campus_k_ss', 10.0),
            stability=sim.pars.get('campus_cl_stability', 0.4),
        )
        people.contacts['clu'].label = 'clu'
        people.contacts['clg'] = CampusClassroomLayer(
            people.contacts['clg'],
            class_groups=people.class_groups_gr,
            k_ts=sim.pars.get('campus_k_ts', 6.0),
            k_ss=sim.pars.get('campus_k_ss', 10.0),
            stability=sim.pars.get('campus_cl_stability', 0.4),
        )
        people.contacts['clg'].label = 'clg'
        people.contacts['of'] = CampusLabLayer(
            people.contacts['of'],
            lab_groups=people.lab_groups,
            k_ts=sim.pars.get('campus_k_ts', 6.0),
            k_ls=sim.pars.get('campus_k_ls', 4.0),
            stability=sim.pars.get('campus_lab_stability', 0.3),
        )

    sc.printv(f'Created {pop_size} people, average age {people.age.mean():0.2f} years', 2, verbose)

    return people


def validate_popdict(popdict, pars, verbose=True):
    '''
    Check that the popdict is the correct type, has the correct keys, and has
    the correct length
    '''

    # Check it's the right type
    try:
        popdict.keys() # Although not used directly, this is used in the error message below, and is a good proxy for a dict-like object
    except Exception as E:
        errormsg = f'The popdict should be a dictionary or cv.People object, but instead is {type(popdict)}'
        raise TypeError(errormsg) from E

    # Check keys and lengths
    required_keys = ['uid', 'age', 'sex']
    popdict_keys = popdict.keys()
    pop_size = pars['pop_size']
    for key in required_keys:

        if key not in popdict_keys:
            errormsg = f'Could not find required key "{key}" in popdict; available keys are: {sc.strjoin(popdict.keys())}'
            sc.KeyNotFoundError(errormsg)

        actual_size = len(popdict[key])
        if actual_size != pop_size:
            errormsg = f'Could not use supplied popdict since key {key} has length {actual_size}, but all keys must have length {pop_size}'
            raise ValueError(errormsg)

        isnan = np.isnan(popdict[key]).sum()
        if isnan:
            errormsg = f'Population not fully created: {isnan:,} NaNs found in {key}. This can be caused by calling cv.People() instead of cv.make_people().'
            raise ValueError(errormsg)

    if ('contacts' not in popdict_keys) and (not hasattr(popdict, 'contacts')) and verbose:
        warnmsg = 'No contacts found. Please remember to add contacts before running the simulation.'
        cvm.warn(warnmsg)

    return


def make_randpop(pars, use_age_data=True, use_household_data=True, sex_ratio=0.5, microstructure='random', **kwargs):
    '''
    Make a random population, with contacts.

    This function returns a "popdict" dictionary, which has the following (required) keys:

        - uid: an array of (usually consecutive) integers of length N, uniquely identifying each agent
        - age: an array of floats of length N, the age in years of each agent
        - sex: an array of integers of length N (not currently used, so does not have to be binary)
        - contacts: list of length N listing the contacts; see make_random_contacts() for details
        - layer_keys: a list of strings representing the different contact layers in the population; see make_random_contacts() for details

    Args:
        pars (dict): the parameter dictionary or simulation object
        use_age_data (bool): whether to use location-specific age data
        use_household_data (bool): whether to use location-specific household size data
        sex_ratio (float): proportion of the population that is male (not currently used)
        microstructure (bool): whether or not to use the microstructuring algorithm to group contacts
        kwargs (dict): passed to contact creation method (e.g., make_hybrid_contacts)

    Returns:
        popdict (dict): a dictionary representing the population, with the following keys for a population of N agents with M contacts between them:
    '''

    pop_size = int(pars['pop_size']) # Number of people
    pop_pars = pars.pars if hasattr(pars, 'pars') else pars # Support being passed either a Sim or a dict

    # Load age data and household demographics based on 2018 Seattle demographics by default, or country if available
    age_data = cvd.default_age_data
    location = pars['location']
    if location is not None:
        if pars['verbose']:
            print(f'Loading location-specific data for "{location}"')
        if use_age_data:
            try:
                age_data = cvdata.get_age_distribution(location)
            except ValueError as E:
                warnmsg = f'Could not load age data for requested location "{location}" ({str(E)}), using default'
                cvm.warn(warnmsg)
        if use_household_data:
            try:
                household_size = cvdata.get_household_size(location)
                if 'h' in pars['contacts']:
                    pars['contacts']['h'] = household_size - 1 # Subtract 1 because e.g. each person in a 3-person household has 2 contacts
                elif pars['verbose']:
                    keystr = ', '.join(list(pars['contacts'].keys()))
                    warnmsg = f'Not loading household size for "{location}" since no "h" key; keys are "{keystr}". Try "hybrid" population type?'
                    cvm.warn(warnmsg)
            except ValueError as E:
                if pars['verbose']>1: # These don't exist for many locations, so skip the warning by default
                    warnmsg = f'Could not load household size data for requested location "{location}" ({str(E)}), using default'
                    cvm.warn(warnmsg)

    # Handle sexes and ages
    uids           = np.arange(pop_size, dtype=cvd.default_int)
    sexes          = np.random.binomial(1, sex_ratio, pop_size)
    age_data_min   = age_data[:,0]
    age_data_max   = age_data[:,1] + 1 # Since actually e.g. 69.999
    age_data_range = age_data_max - age_data_min
    age_data_prob  = age_data[:,2]
    age_data_prob /= age_data_prob.sum() # Ensure it sums to 1
    age_bins       = cvu.n_multinomial(age_data_prob, pop_size) # Choose age bins
    ages           = age_data_min[age_bins] + age_data_range[age_bins]*np.random.random(pop_size) # Uniformly distribute within this age bin

    # Store output
    popdict = {}
    popdict['uid'] = uids
    popdict['age'] = ages
    popdict['sex'] = sexes
    popdict['role'] = np.full(pop_size, -1, dtype=cvd.default_int)


    if microstructure == 'random':
        contacts = dict()
        for lkey,n in pars['contacts'].items():
            contacts[lkey] = make_random_contacts(pop_size, n, **kwargs)
    elif microstructure == 'hybrid':
        contacts = make_hybrid_contacts(pop_size, ages, pars['contacts'], **kwargs)
    elif microstructure == 'campus':
        campus_age_data = np.array(pop_pars.get('campus_age_data', cvd.default_age_data), dtype=cvd.default_float)
        age_data_min   = campus_age_data[:, 0]
        age_data_max   = campus_age_data[:, 1] + 1
        age_data_range = age_data_max - age_data_min
        age_data_prob  = campus_age_data[:, 2].astype(cvd.default_float)
        age_data_prob /= age_data_prob.sum()
        campus_age_counts = pop_pars.get('campus_age_counts', None)
        if campus_age_counts is not None:
            counts = np.asarray(campus_age_counts, dtype=cvd.default_int)
            if (counts.ndim != 1 or len(counts) != len(campus_age_data)
                    or np.any(counts < 0) or int(counts.sum()) != pop_size):
                raise ValueError('campus_age_counts must be nonnegative integers matching campus_age_data bins and pop_size')
            age_bins = np.repeat(np.arange(len(counts)), counts)
            np.random.shuffle(age_bins)
        else:
            age_bins = cvu.n_multinomial(age_data_prob, pop_size)
        ages = age_data_min[age_bins] + age_data_range[age_bins] * np.random.random(pop_size)
        popdict['age'] = ages

        registry_metadata = {}
        contacts, role, student_level, class_groups_ug, class_groups_gr, lab_groups = make_campus_contacts(
            pop_size=pop_size,
            ages=ages,
            sexes=sexes,
            contacts=pars['contacts'],
            ug_age_window=pop_pars.get('campus_undergrad_age_window', [17, 24]),
            gr_age_window=pop_pars.get('campus_grad_age_window', [24, 31]),
            worker_age_window=pop_pars.get('campus_worker_age_window', [31, 66]),
            teacher_ratio=pop_pars.get('campus_teacher_ratio', 0.08),
            staff_ratio=pop_pars.get('campus_staff_ratio', 0.12),
            p_ug_in_lab=pop_pars.get('campus_p_ug_in_lab', 0.10),
            p_grad_in_class=pop_pars.get('campus_p_grad_in_class', 0.35),
            class_size_mean=pop_pars.get('campus_class_size_mean', 40),
            class_size_std=pop_pars.get('campus_class_size_std', 6),
            class_size_min=pop_pars.get('campus_class_size_min', 30),
            class_size_max=pop_pars.get('campus_class_size_max', 55),
            teachers_per_class=pop_pars.get('campus_teachers_per_class', 1),
            registry_metadata=registry_metadata,
        )
        popdict['role'] = role
        popdict['student_level'] = student_level
        popdict['class_groups_ug'] = class_groups_ug
        popdict['class_groups_gr'] = class_groups_gr
        popdict['lab_groups'] = lab_groups
        popdict['campus_registry_metadata'] = registry_metadata
    else: # pragma: no cover
        errormsg = f'Microstructure type "{microstructure}" not found; choices are random, hybrid, or campus'
        raise NotImplementedError(errormsg)


    popdict['contacts']   = contacts
    popdict['layer_keys'] = list(pars['contacts'].keys())

    return popdict


def _tidy_edgelist(p1, p2, mapping):
    ''' Helper function to convert lists to arrays and optionally map arrays '''
    p1 = np.array(p1, dtype=cvd.default_int)
    p2 = np.array(p2, dtype=cvd.default_int)
    if mapping is not None:
        mapping = np.array(mapping, dtype=cvd.default_int)
        p1 = mapping[p1]
        p2 = mapping[p2]
    output = dict(p1=p1, p2=p2)
    return output


def make_random_contacts(pop_size, n, overshoot=1.2, dispersion=None, mapping=None):
    '''
    Make random static contacts for a single layer as an edgelist.

    Args:
        pop_size   (int)   : number of agents to create contacts between (N)
        n          (int) : the average number of contacts per person for this layer
        overshoot  (float) : to avoid needing to take multiple Poisson draws
        dispersion (float) : if not None, use a negative binomial distribution with this dispersion parameter instead of Poisson to make the contacts
        mapping    (array) : optionally map the generated indices onto new indices

    Returns:
        Dictionary of two arrays defining UIDs of the edgelist (sources and targets)

    New in 3.1.1: optimized and updated arguments.
    '''

    # Preprocessing
    pop_size = int(pop_size) # Number of people
    p1 = [] # Initialize the "sources"
    p2 = [] # Initialize the "targets"

    # Precalculate contacts
    n_all_contacts  = int(pop_size*n*overshoot) # The overshoot is used so we won't run out of contacts if the Poisson draws happen to be higher than the expected value
    all_contacts    = cvu.choose_r(max_n=pop_size, n=n_all_contacts) # Choose people at random
    if dispersion is None:
        p_count = cvu.n_poisson(n, pop_size) # Draw the number of Poisson contacts for this person
    else:
        p_count = cvu.n_neg_binomial(rate=n, dispersion=dispersion, n=pop_size) # Or, from a negative binomial
    p_count = np.array((p_count/2.0).round(), dtype=cvd.default_int)

    # Make contacts
    count = 0
    for p in range(pop_size):
        n_contacts = p_count[p]
        these_contacts = all_contacts[count:count+n_contacts] # Assign people
        count += n_contacts
        p1.extend([p]*n_contacts)
        p2.extend(these_contacts)

    # Tidy up
    output = _tidy_edgelist(p1, p2, mapping)

    return output


def make_microstructured_contacts(pop_size, cluster_size, mapping=None):
    '''
    Create microstructured contacts -- i.e. for households.

    Args:
        pop_size (int): total number of people
        cluster_size (int): the average size of each cluster (Poisson-sampled)

    New in version 3.1.1: optimized updated arguments.
    '''

    # Preprocessing -- same as above
    pop_size = int(pop_size) # Number of people
    p1 = [] # Initialize the "sources"
    p2 = [] # Initialize the "targets"

    # Initialize
    n_remaining = pop_size # Make clusters - each person belongs to one cluster

    # Loop over the clusters
    cluster_id = -1
    while n_remaining > 0:
        cluster_id += 1 # Assign cluster id
        this_cluster =  cvu.poisson(cluster_size)  # Sample the cluster size
        if this_cluster > n_remaining:
            this_cluster = n_remaining

        # Indices of people in this cluster
        cluster_indices = (pop_size-n_remaining) + np.arange(this_cluster)
        for source in cluster_indices: # Add symmetric pairwise contacts in each cluster
            targets = set()
            for target in cluster_indices:
                if target > source:
                    targets.add(target)
            p1.extend([source]*len(targets))
            p2.extend(list(targets))

        n_remaining -= this_cluster

    # Tidy up
    output = _tidy_edgelist(p1, p2, mapping)

    return output

def _validate_disjoint_windows(*windows):
    ints = [(int(w[0]), int(w[1])) for w in windows]
    for a0, a1 in ints:
        if a1 <= a0:
            raise ValueError(f'Invalid age window [{a0}, {a1})')
    for i in range(len(ints)):
        for j in range(i+1, len(ints)):
            a0, a1 = ints[i]
            b0, b1 = ints[j]
            if max(a0, b0) < min(a1, b1):
                raise ValueError(f'Age windows overlap: [{a0},{a1}) and [{b0},{b1})')


def make_hybrid_contacts(pop_size, ages, contacts, school_ages=None, work_ages=None):
    '''
    Create "hybrid" contacts -- microstructured contacts for households and
    random contacts for schools and workplaces, both of which have extremely
    basic age structure. A combination of both make_random_contacts() and
    make_microstructured_contacts().
    '''

    # Handle inputs and defaults
    contacts = sc.mergedicts({'h':4, 's':20, 'w':20, 'c':20}, contacts) # Ensure essential keys are populated
    if school_ages is None:
        school_ages = [6, 22]
    if work_ages is None:
        work_ages   = [22, 65]

    contacts_dict = {}

    # Start with the household contacts for each person
    contacts_dict['h'] = make_microstructured_contacts(pop_size, contacts['h'])

    # Make community contacts
    contacts_dict['c'] = make_random_contacts(pop_size, contacts['c'])

    # Get the indices of people in each age bin
    ages = np.array(ages)
    s_inds = sc.findinds((ages >= school_ages[0]) * (ages < school_ages[1]))
    w_inds = sc.findinds((ages >= work_ages[0])   * (ages < work_ages[1]))

    # Create the school and work contacts for each person
    contacts_dict['s'] = make_random_contacts(len(s_inds), contacts['s'], mapping=s_inds)
    contacts_dict['w'] = make_random_contacts(len(w_inds), contacts['w'], mapping=w_inds)

    return contacts_dict


class CampusClassroomLayer(cvb.Layer):
    """Dynamic classroom layer using fixed class groups and daily random sampling."""

    def __init__(self, layer, class_groups, k_ts=6.0, k_ss=10.0, stability=0.4):
        # 保留原层名（clu 或 clg），避免两层都显示为 cl
        layer_label = layer.label if hasattr(layer, 'label') and layer.label else 'cl'
        super().__init__(label=layer_label)

        self['p1'] = np.array(layer['p1'], dtype=cvd.default_int)
        self['p2'] = np.array(layer['p2'], dtype=cvd.default_int)
        if 'beta' in layer:
            self['beta'] = np.array(layer['beta'], dtype=cvd.default_float)
        else:
            self['beta'] = np.ones(len(self['p1']), dtype=cvd.default_float)

        self.class_groups = class_groups
        self.k_ts = float(k_ts)
        self.k_ss = float(k_ss)
        self.stability = float(stability)

    def _sample_ss_edges(self, students, n_edges):
        if len(students) < 2 or n_edges <= 0:
            return [], []
        p1 = np.random.choice(students, size=n_edges, replace=True)
        p2 = np.random.choice(students, size=n_edges, replace=True)
        valid = p1 != p2
        return p1[valid].tolist(), p2[valid].tolist()

    def _sample_ts_edges(self, teachers, students):
        if len(teachers) == 0 or len(students) == 0 or self.k_ts <= 0:
            return [], []
        p1, p2 = [], []
        for t in teachers:
            n_t = cvu.poisson(self.k_ts)
            if n_t > 0:
                s = np.random.choice(students, size=n_t, replace=True)
                p1.extend([int(t)] * n_t)
                p2.extend(s.tolist())
        return p1, p2

    def update(self, people):
        old_n = len(self)
        keep_n = int(round(self.stability * old_n)) if old_n > 0 else 0

        keep_p1, keep_p2 = [], []
        if keep_n > 0:
            keep_inds = cvu.choose(old_n, keep_n)
            keep_p1 = self['p1'][keep_inds].tolist()
            keep_p2 = self['p2'][keep_inds].tolist()

        new_p1, new_p2 = [], []
        for grp in self.class_groups:
            students = grp['students']
            teachers = grp['teachers']

            ts_p1, ts_p2 = self._sample_ts_edges(teachers, students)
            new_p1.extend(ts_p1)
            new_p2.extend(ts_p2)

            n_ss = int(round(len(students) * max(self.k_ss, 0) / 2.0))
            ss_p1, ss_p2 = self._sample_ss_edges(students, n_ss)
            new_p1.extend(ss_p1)
            new_p2.extend(ss_p2)

        all_p1 = np.array(keep_p1 + new_p1, dtype=cvd.default_int)
        all_p2 = np.array(keep_p2 + new_p2, dtype=cvd.default_int)

        # Undirected canonicalization + remove self-loop + dedup
        if len(all_p1):
            a = np.minimum(all_p1, all_p2)
            b = np.maximum(all_p1, all_p2)
            valid = a != b
            a = a[valid]
            b = b[valid]

            if len(a):
                pairs = np.column_stack((a, b))
                uniq_pairs = np.unique(pairs, axis=0)
                all_p1 = uniq_pairs[:, 0].astype(cvd.default_int)
                all_p2 = uniq_pairs[:, 1].astype(cvd.default_int)
            else:
                all_p1 = np.empty(0, dtype=cvd.default_int)
                all_p2 = np.empty(0, dtype=cvd.default_int)

        self['p1'] = all_p1
        self['p2'] = all_p2
        self['beta'] = np.ones(len(self['p1']), dtype=cvd.default_float)
        return

class CampusLabLayer(cvb.Layer):
    """Dynamic lab layer: stable membership, random daily edges."""
    def __init__(self, layer, lab_groups, k_ts=4.0, k_ls=4.0, stability=0.3):
        super().__init__(label='of')
        self['p1'] = np.array(layer['p1'], dtype=cvd.default_int)
        self['p2'] = np.array(layer['p2'], dtype=cvd.default_int)
        self['beta'] = np.ones(len(self['p1']), dtype=cvd.default_float)
        self.lab_groups = lab_groups
        self.k_ts = float(k_ts)
        self.k_ls = float(k_ls)
        self.stability = float(stability)

    def update(self, people):
        old_n = len(self)
        keep_n = int(round(self.stability * old_n)) if old_n > 0 else 0

        keep_p1, keep_p2 = [], []
        if keep_n > 0:
            keep_inds = cvu.choose(old_n, keep_n)
            keep_p1 = self['p1'][keep_inds].tolist()
            keep_p2 = self['p2'][keep_inds].tolist()

        p1_new, p2_new = [], []
        for grp in self.lab_groups:
            teachers = grp['teachers']
            students = grp['students']
            if len(teachers) and len(students):
                for t in teachers:
                    n_t = cvu.poisson(self.k_ts)
                    if n_t > 0:
                        ss = np.random.choice(students, size=n_t, replace=True)
                        p1_new.extend([int(t)] * n_t)
                        p2_new.extend(ss.tolist())
            if len(students) > 1 and self.k_ls > 0:
                n_ss = int(round(len(students) * self.k_ls / 2.0))
                a = np.random.choice(students, size=n_ss, replace=True)
                b = np.random.choice(students, size=n_ss, replace=True)
                valid = a != b
                p1_new.extend(a[valid].tolist())
                p2_new.extend(b[valid].tolist())

        all_p1 = np.array(keep_p1 + p1_new, dtype=cvd.default_int)
        all_p2 = np.array(keep_p2 + p2_new, dtype=cvd.default_int)

        if len(all_p1):
            a = np.minimum(all_p1, all_p2)
            b = np.maximum(all_p1, all_p2)
            valid = a != b
            a, b = a[valid], b[valid]
            if len(a):
                pairs = np.column_stack((a, b))
                pairs = np.unique(pairs, axis=0)
                self['p1'] = pairs[:, 0].astype(cvd.default_int)
                self['p2'] = pairs[:, 1].astype(cvd.default_int)
            else:
                self['p1'] = np.empty(0, dtype=cvd.default_int)
                self['p2'] = np.empty(0, dtype=cvd.default_int)
        else:
            self['p1'] = np.empty(0, dtype=cvd.default_int)
            self['p2'] = np.empty(0, dtype=cvd.default_int)

        self['beta'] = np.ones(len(self['p1']), dtype=cvd.default_float)
        return


def make_campus_contacts(pop_size, ages, sexes, contacts,
                         role=None,
                         student_level=None,
                         ug_age_window=(17, 24),
                         gr_age_window=(24, 31),
                         worker_age_window=(31, 66),
                         teacher_ratio=0.08,
                         staff_ratio=0.12,
                         p_ug_in_lab=0.10,
                         p_grad_in_class=0.35,
                         class_size_mean=40,
                         class_size_std=6,
                         class_size_min=30,
                         class_size_max=55,
                         teachers_per_class=1, *, registry_metadata=None):
    contacts = sc.mergedicts({'d': 6, 'clu': 25, 'clg': 12, 'of': 6, 'ta': 3, 'cm': 12}, contacts)

    if teacher_ratio < 0 or staff_ratio < 0 or teacher_ratio + staff_ratio > 1:
        raise ValueError('campus_teacher_ratio and campus_staff_ratio must be >=0 and sum <= 1')

    _validate_disjoint_windows(ug_age_window, gr_age_window, worker_age_window)

    ages = np.asarray(ages)
    sexes = np.asarray(sexes, dtype=cvd.default_int)
    all_inds = np.arange(pop_size, dtype=cvd.default_int)

    ug_inds = sc.findinds((ages >= ug_age_window[0]) * (ages < ug_age_window[1]))
    gr_inds = sc.findinds((ages >= gr_age_window[0]) * (ages < gr_age_window[1]))
    student_inds = np.union1d(ug_inds, gr_inds).astype(cvd.default_int)
    non_student_inds = np.setdiff1d(all_inds, student_inds).astype(cvd.default_int)

    worker_pool = sc.findinds((ages >= worker_age_window[0]) * (ages < worker_age_window[1]))
    worker_pool = np.intersect1d(worker_pool, non_student_inds).astype(cvd.default_int)

    n_teacher_target = int(round(pop_size * teacher_ratio))
    n_staff_target = int(round(pop_size * staff_ratio))

    n_teacher = min(n_teacher_target, len(worker_pool))
    teacher_inds = np.random.choice(worker_pool, size=n_teacher, replace=False).astype(cvd.default_int) if n_teacher > 0 else np.empty(0, dtype=cvd.default_int)
    remain_pool = np.setdiff1d(worker_pool, teacher_inds).astype(cvd.default_int)
    n_staff = min(n_staff_target, len(remain_pool))
    staff_inds = np.random.choice(remain_pool, size=n_staff, replace=False).astype(cvd.default_int) if n_staff > 0 else np.empty(0, dtype=cvd.default_int)

    # Export existing registration draws without changing network generation or RNG.
    if registry_metadata is not None:
        registry_metadata.update(student_indices=student_inds.copy(),
                                 teacher_indices=teacher_inds.copy(),
                                 staff_indices=staff_inds.copy())

    role_out = np.full(pop_size, 2, dtype=cvd.default_int)  # default non-student role
    role_out[student_inds] = 0
    role_out[teacher_inds] = 1
    role_out[staff_inds] = 2

    student_level_out = np.full(pop_size, 2, dtype=cvd.default_int)  # non-student
    student_level_out[ug_inds] = 0
    student_level_out[gr_inds] = 1

    def _draw_class_size(n_remaining):
        raw = int(round(np.random.normal(class_size_mean, class_size_std)))
        raw = max(class_size_min, min(class_size_max, raw))
        return min(max(raw, 1), n_remaining)

    contacts_dict = {}

    # d: students-only dorm by sex
    d_edges = []
    for sx in [0, 1]:
        sx_inds = student_inds[sexes[student_inds] == sx]
        if len(sx_inds):
            d_edges.append(make_microstructured_contacts(len(sx_inds), contacts['d'], mapping=sx_inds))
    if d_edges:
        p1 = np.concatenate([e['p1'] for e in d_edges]) if len(d_edges) else np.empty(0, dtype=cvd.default_int)
        p2 = np.concatenate([e['p2'] for e in d_edges]) if len(d_edges) else np.empty(0, dtype=cvd.default_int)
        contacts_dict['d'] = dict(p1=p1.astype(cvd.default_int), p2=p2.astype(cvd.default_int))
    else:
        contacts_dict['d'] = dict(p1=np.empty(0, dtype=cvd.default_int), p2=np.empty(0, dtype=cvd.default_int))

    # class groups: UG only / GR only
    class_groups_ug = []
    if len(ug_inds):
        shuffled = np.array(ug_inds, dtype=cvd.default_int).copy()
        np.random.shuffle(shuffled)
        cursor, class_id = 0, 0
        while cursor < len(shuffled):
            csize = _draw_class_size(len(shuffled) - cursor)
            students = shuffled[cursor:cursor+csize]
            cursor += csize
            n_teach = max(1, int(cvu.poisson(max(teachers_per_class - 1, 0))) + 1)
            if len(teacher_inds):
                rep = len(teacher_inds) < n_teach
                teachers = np.random.choice(teacher_inds, size=n_teach, replace=rep).astype(cvd.default_int)
            else:
                teachers = np.empty(0, dtype=cvd.default_int)
            class_groups_ug.append(dict(class_id=class_id, students=students, teachers=teachers))
            class_id += 1

    class_groups_gr = []
    gr_class_inds = gr_inds[cvu.binomial_arr(np.full(len(gr_inds), p_grad_in_class))] if len(gr_inds) else np.empty(0, dtype=cvd.default_int)
    if len(gr_class_inds):
        shuffled = np.array(gr_class_inds, dtype=cvd.default_int).copy()
        np.random.shuffle(shuffled)
        cursor, class_id = 0, 0
        while cursor < len(shuffled):
            csize = _draw_class_size(len(shuffled) - cursor)
            students = shuffled[cursor:cursor+csize]
            cursor += csize
            n_teach = max(1, int(cvu.poisson(max(teachers_per_class - 1, 0))) + 1)
            if len(teacher_inds):
                rep = len(teacher_inds) < n_teach
                teachers = np.random.choice(teacher_inds, size=n_teach, replace=rep).astype(cvd.default_int)
            else:
                teachers = np.empty(0, dtype=cvd.default_int)
            class_groups_gr.append(dict(class_id=class_id, students=students, teachers=teachers))
            class_id += 1

    contacts_dict['clu'] = dict(p1=np.empty(0, dtype=cvd.default_int), p2=np.empty(0, dtype=cvd.default_int))
    contacts_dict['clg'] = dict(p1=np.empty(0, dtype=cvd.default_int), p2=np.empty(0, dtype=cvd.default_int))

    # lab groups (stable membership): GR + sampled UG
    ug_lab_inds = ug_inds[cvu.binomial_arr(np.full(len(ug_inds), p_ug_in_lab))] if len(ug_inds) else np.empty(0, dtype=cvd.default_int)
    lab_student_pool = np.unique(np.concatenate([gr_inds, ug_lab_inds])).astype(cvd.default_int) if (len(gr_inds) or len(ug_lab_inds)) else np.empty(0, dtype=cvd.default_int)
    lab_groups = []
    if len(teacher_inds):
        for t in teacher_inds:
            if len(lab_student_pool):
                n_pick = max(1, int(cvu.poisson(contacts['of'])))
                rep = len(lab_student_pool) < n_pick
                st = np.random.choice(lab_student_pool, size=n_pick, replace=rep).astype(cvd.default_int)
            else:
                st = np.empty(0, dtype=cvd.default_int)
            lab_groups.append(dict(teachers=np.array([t], dtype=cvd.default_int), students=st))

    contacts_dict['of'] = dict(p1=np.empty(0, dtype=cvd.default_int), p2=np.empty(0, dtype=cvd.default_int))

    # ta: all non-student as microstructured household-like network
    contacts_dict['ta'] = make_microstructured_contacts(len(non_student_inds), contacts['ta'], mapping=non_student_inds) if len(non_student_inds) else dict(
        p1=np.empty(0, dtype=cvd.default_int), p2=np.empty(0, dtype=cvd.default_int)
    )

    contacts_dict['cm'] = make_random_contacts(pop_size, contacts['cm'])

    return contacts_dict, role_out, student_level_out, class_groups_ug, class_groups_gr, lab_groups




def make_synthpop(sim=None, popdict=None, layer_mapping=None, community_contacts=None, **kwargs): # pragma: no cover
    '''
    Make a population using SynthPops, including contacts.

    Usually called automatically, but can also be called manually. Either a simulation
    object or a population must be supplied; if a population is supplied, transform
    it into the correct format; otherwise, create the population and then transform it.

    Args:
        sim (Sim): a Covasim simulation object
        popdict (dict/Pop/People): a pre-generated SynthPops population (otherwise, create a new one)
        layer_mapping (dict): a custom mapping from SynthPops layers to Covasim layers
        community_contacts (int): if a simulation is not supplied, create this many community contacts on average
        kwargs (dict): passed to sp.make_population()

    **Example**::

        sim = cv.Sim(pop_type='synthpops')
        sim.popdict = cv.make_synthpop(sim)
        sim.run()
    '''
    try:
        import synthpops as sp # Optional import
    except ModuleNotFoundError as E: # pragma: no cover
        errormsg = 'Please install the optional SynthPops module first, e.g. pip install synthpops' # Also caught in make_people()
        raise ModuleNotFoundError(errormsg) from E

    # Handle layer mapping
    default_layer_mapping = {'H':'h', 'S':'s', 'W':'w', 'C':'c', 'LTCF':'l'} # Remap keys from old names to new names
    layer_mapping = sc.mergedicts(default_layer_mapping, layer_mapping)

    # Handle community contacts
    if community_contacts is None:
        if sim is not None:
            community_contacts = sim['contacts']['c']
        else: # pragma: no cover
            errormsg = 'If a simulation is not supplied, the number of community contacts must be specified'
            raise ValueError(errormsg)

    # Main use case -- generate a new population
    pop_size = sim['pop_size']
    if popdict is None:
        if sim is None: # pragma: no cover
            errormsg = 'Either a simulation or a population must be supplied'
            raise ValueError(errormsg)
        people = sp.Pop(n=pop_size, rand_seed=sim['rand_seed'], **kwargs).to_people() # Actually generate it
    else: # Otherwise, convert to a sp.People object (similar to a cv.People object)
        if isinstance(popdict, sp.people.People):
            people = popdict
        elif isinstance(popdict, sp.Pop):
            people = popdict.to_people()
        elif isinstance(popdict, dict):
            people = sp.people.make_people(popdict=popdict)
        elif isinstance(popdict, cvb.BasePeople):
            return popdict # Already the right format
        else:
            errormsg = f'Cannot understand population of type {type(popdict)}: must be dict, sp.Pop, sp.People, or cv.People'
            raise TypeError(errormsg)

    # Convert contacts from SynthPops to Covasim
    people.contacts = cvb.Contacts(**people.contacts)

    # Add community contacts and layer keys
    c_contacts = make_random_contacts(pop_size, community_contacts)
    people.contacts.add_layer(c=c_contacts)
    people['layer_keys'] = list(layer_mapping.values())

    return people
