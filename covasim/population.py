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
           'make_campus_contacts', 'CampusClassroomLayer', 'make_synthpop']



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
                errormsg = f'Population type "{pop_type}" not found; choices are random, hybrid, or synthpops'
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

        people = cvppl.People(
            sim.pars,
            uid=popdict['uid'],
            age=popdict['age'],
            sex=popdict['sex'],
            role=popdict['role'],
            contacts=popdict['contacts'],
        )

    # Attach campus classroom dynamic layer and persistent class groups
    if pop_type == 'campus' and 'class_groups' in popdict:
        people.class_groups = popdict['class_groups']
        people.contacts['cl'] = CampusClassroomLayer(
            people.contacts['cl'],
            class_groups=people.class_groups,
            k_ts=sim.pars.get('campus_k_ts', 6.0),
            k_ss=sim.pars.get('campus_k_ss', 10.0),
            stability=sim.pars.get('campus_cl_stability', 0.4),
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
        contacts, role, class_groups = make_campus_contacts(
            pop_size=pop_size,
            ages=ages,
            sexes=sexes,
            contacts=pars['contacts'],
            student_age=pop_pars.get('campus_student_age', [17, 26]),
            teacher_age=pop_pars.get('campus_teacher_age', [26, 65]),
            class_size_mean=pop_pars.get('campus_class_size_mean', 40),
            class_size_std=pop_pars.get('campus_class_size_std', 6),
            class_size_min=pop_pars.get('campus_class_size_min', 30),
            class_size_max=pop_pars.get('campus_class_size_max', 55),
            teachers_per_class=pop_pars.get('campus_teachers_per_class', 3),
        )
        popdict['role'] = role
        popdict['class_groups'] = class_groups
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
        super().__init__(label='cl')
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


def make_campus_contacts(pop_size, ages, sexes, contacts,
                         role=None,
                         student_age=(17, 26),
                         teacher_age=(26, 65),
                         class_size_mean=40,
                         class_size_std=6,
                         class_size_min=30,
                         class_size_max=55,
                         teachers_per_class=3):
    """
    Campus layers:
    d  = dormitory (student only, sex-separated clusters)
    cl = classroom (dynamic layer; class groups are fixed)
    of = office/lab (teacher-student random bipartite)
    ta = teacher apartment (each apartment has >=1 teacher)
    cm = public/community random (dynamic if configured)
    """
    contacts = sc.mergedicts({'d': 6, 'cl': 25, 'of': 6, 'ta': 3, 'cm': 12}, contacts)

    if role is None:
        role = np.full(pop_size, -1, dtype=cvd.default_int)
        ages = np.asarray(ages)
        stu = sc.findinds((ages >= student_age[0]) * (ages < student_age[1]))
        tea = sc.findinds((ages >= teacher_age[0]) * (ages < teacher_age[1]))
        role[stu] = 0
        role[tea] = 1
        other = np.setdiff1d(np.arange(pop_size), np.concatenate([stu, tea]))
        role[other] = 2

    role = np.asarray(role, dtype=cvd.default_int)
    sexes = np.asarray(sexes, dtype=cvd.default_int)

    student_inds = np.where(role == 0)[0]
    teacher_inds = np.where(role == 1)[0]
    staff_inds = np.where(role == 2)[0]

    def _merge_edges(edge_list):
        p1_all, p2_all = [], []
        for e in edge_list:
            if e is None:
                continue
            if len(e['p1']):
                p1_all.append(e['p1'])
                p2_all.append(e['p2'])
        if len(p1_all) == 0:
            return dict(
                p1=np.empty(0, dtype=cvd.default_int),
                p2=np.empty(0, dtype=cvd.default_int),
            )
        return dict(
            p1=np.concatenate(p1_all).astype(cvd.default_int),
            p2=np.concatenate(p2_all).astype(cvd.default_int),
        )

    def _draw_class_size(n_remaining):
        raw = int(round(np.random.normal(class_size_mean, class_size_std)))
        raw = max(class_size_min, min(class_size_max, raw))
        return min(max(raw, 1), n_remaining)

    contacts_dict = {}

    # d: dorm (students only, split by sex)
    d_edges = []
    for sx in [0, 1]:
        sx_inds = student_inds[sexes[student_inds] == sx]
        if len(sx_inds):
            d_edges.append(make_microstructured_contacts(len(sx_inds), contacts['d'], mapping=sx_inds))
    contacts_dict['d'] = _merge_edges(d_edges)

    # Build fixed class groups (for dynamic classroom layer)
    class_groups = []
    if len(student_inds) > 0:
        shuffled = np.array(student_inds, dtype=cvd.default_int).copy()
        np.random.shuffle(shuffled)

        cursor = 0
        class_id = 0
        while cursor < len(shuffled):
            n_remaining = len(shuffled) - cursor
            csize = _draw_class_size(n_remaining)
            students = shuffled[cursor:cursor+csize]
            cursor += csize

            n_teachers = max(1, int(cvu.poisson(max(teachers_per_class - 1, 0))) + 1)
            if len(teacher_inds) > 0:
                replace = len(teacher_inds) < n_teachers
                teachers = np.random.choice(teacher_inds, size=n_teachers, replace=replace).astype(cvd.default_int)
            else:
                teachers = np.empty(0, dtype=cvd.default_int)

            members = np.unique(np.concatenate((students, teachers))).astype(cvd.default_int)
            class_groups.append(dict(
                class_id=class_id,
                students=np.array(students, dtype=cvd.default_int),
                teachers=np.array(teachers, dtype=cvd.default_int),
                members=members,
            ))
            class_id += 1

    # cl: start empty; updated daily by CampusClassroomLayer.update()
    contacts_dict['cl'] = dict(
        p1=np.empty(0, dtype=cvd.default_int),
        p2=np.empty(0, dtype=cvd.default_int),
    )

    # of: office/lab (teacher-student bipartite random)
    of_p1, of_p2 = [], []
    if len(teacher_inds) and len(student_inds):
        for t in teacher_inds:
            n_t = cvu.poisson(contacts['of'])
            if n_t > 0:
                st = np.random.choice(student_inds, size=n_t, replace=True)
                of_p1.extend([int(t)] * n_t)
                of_p2.extend(st.tolist())
    contacts_dict['of'] = _tidy_edgelist(of_p1, of_p2, mapping=None)

    # ta: teacher apartments
    ta_p1, ta_p2 = [], []
    apt_pool = np.concatenate([teacher_inds, staff_inds]) if len(staff_inds) else np.array(teacher_inds, dtype=cvd.default_int)
    for t in teacher_inds:
        apt_size = max(2, int(cvu.poisson(contacts['ta'])))
        n_other = apt_size - 1
        if n_other <= 0:
            continue
        candidates = apt_pool[apt_pool != t]
        if len(candidates) == 0:
            continue
        replace = len(candidates) < n_other
        others = np.random.choice(candidates, size=n_other, replace=replace).astype(cvd.default_int)
        group = np.concatenate([[t], others])
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                ta_p1.append(int(group[i]))
                ta_p2.append(int(group[j]))
    contacts_dict['ta'] = _tidy_edgelist(ta_p1, ta_p2, mapping=None)

    # cm: public/community
    contacts_dict['cm'] = make_random_contacts(pop_size, contacts['cm'])

    return contacts_dict, role, class_groups



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
