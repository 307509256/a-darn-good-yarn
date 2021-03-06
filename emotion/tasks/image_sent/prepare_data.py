# Prepare the data (parse, convert to tfrecords, download, etc.)

import argparse
from collections import defaultdict, Counter
import json
import numpy as np
import os
import pickle
from PIL import Image
from pprint import pprint
import random
import re
import tensorflow as tf
import urllib

from core.utils.utils import read_yaml, get_grayscale_hist, get_color_hist
from core.utils.MovieReader import MovieReader


### SENTIBANK + MVSO
# Sentibank - bi_concepts1553: mapping ajdective noun pairs to sentiment
SENTIBANK_FLICKR_PATH = 'data/Sentibank/Flickr/'
SENTIBANK_BC_PATH = 'data/Sentibank/Flickr/bi_concepts1553'
EMOLEX_PATH = 'data/emolex/NRC-emotion-lexicon-wordlevel-alphabetized-v0.92.txt'

# MVSO dataset - mutlilingual, larger version of Sentibank VSO; also has emotions
MVSO_PATH = 'data/MVSO'
MVSO_BC_PATH = 'data/MVSO/imgs/'

# Labels
SENT_BICLASS_LABEL2INT = {'neg': 0, 'pos': 1}
SENT_TRICLASS_LABEL2INT = {'neg':0, 'neutral':1, 'pos':2}
SENTIBANK_EMO_LABEL2INT = {'anger': 0, 'anticipation': 1, 'disgust': 2, 'fear': 3,
             'joy': 4, 'sadness': 5, 'surprise': 6, 'trust': 7}
MVSO_EMO_LABEL2INT = {'ecstasy': 0, 'joy': 1, 'serenity': 2,
                      'admiration': 3, 'trust': 4, 'acceptance': 5,
                      'terror': 6, 'fear': 7, 'apprehension': 8,
                      'amazement': 9, 'surprise': 10, 'distraction': 11,
                      'grief': 12, 'sadness': 13, 'pensiveness': 14,
                      'loathing': 15, 'disgust': 16, 'boredom': 17,
                      'rage': 18, 'anger': 19, 'annoyance': 20,
                      'vigilance': 21, 'anticipation': 22, 'interest': 23}

### OTHER
# You dataset - 20k images with emotions
YOU_IMEMO_PATH = 'data/you_imemo/agg'

# Plutchik
PLUTCHIK_PATH = 'data/plutchik'

# AVA
AVA_PATH = 'data/AVA'

########################################################################################################################
# Sentibank
########################################################################################################################
# Getting data structures for each objective
def get_Sentibank_bc2sent():
    """
    Return dictionary mapping bi_concept to positive-negative polarity values

    Example line: frail_hand [sentiment: -1.44] [#imgs: 358]
        - note: number of imgs is number returned by Flickr - not necessarily what's in dataset
    """
    bc2sent_and_count = {}
    with open('data/Sentibank/VSO/3244ANPs.txt', 'r') as f:
        for line in f.readlines():
            line = line.strip()
            if line.endswith(']') and '_' in line:
                m = re.match(r'(.+_.+)\s\[sentiment:\s(.+)\]\s\[#imgs:\s(.+)\]', line)
                bc, sent, _ = m.group(1), float(m.group(2)), int(m.group(3).replace(',', ''))
                bc2sent_and_count[bc] = sent
    return bc2sent_and_count

def get_Sentibank_bc2emo():
    """
    Use emolex to map bi_concept to emotions. Return dict with bc as key, counts of emotions as values.

    Stats: 857 bc's with at least one emotion (57.3%) , 696 emotions without any emotions
    """
    def get_emolex():
        word2emotions = defaultdict(set)
        f = open(EMOLEX_PATH, 'rb')
        i = 0
        for line in f.readlines():
            if i > 45:          # Previous lines are readme
                word, emotion, flag = line.strip('\n').split()
                if emotion == 'positive' or emotion == 'negative':
                    continue
                if int(flag) == 1:
                    word2emotions[word].add(emotion)
            i += 1
        return word2emotions

    bc2emo = defaultdict(list)
    bc2img_fps = get_all_VSO_img_fps('Sentibank')
    word2emotions = get_emolex()
    for bc, _ in bc2img_fps.items():
        adj, noun = bc.split('_')
        if adj in word2emotions:
            for emotion in word2emotions[adj]:
                bc2emo[bc].append(emotion)
        if noun in word2emotions:
            for emotion in word2emotions[noun]:
                bc2emo[bc].append(emotion)
        bc2emo[bc] = Counter(bc2emo[bc])

    return bc2emo

def get_Sentibank_bc2idx():
    """Return dictionary mapping biconcept to idx"""
    bc2idx = {}
    for i, bc in enumerate(sorted([d for d in os.listdir(SENTIBANK_BC_PATH) if not d.startswith('.')])):
        bc2idx[bc] = i
    return bc2idx

########################################################################################################################
# MVSO
########################################################################################################################
def get_MVSO_bc2sent():
    """Return dict from bi_concept to sentiment value"""
    bc2sentiment = {}
    with open(os.path.join(MVSO_PATH, 'mvso_sentiment', 'english.csv'), 'r') as f:
        for line in f.readlines():
            bc, sentiment = line.strip().split(',')
            bc2sentiment[bc] = float(sentiment)
    return bc2sentiment

def get_MVSO_bc2emo2val():
    """Return dict from bi_concept to dict from emotion to score"""
    bc2emotion2value = defaultdict(dict)
    col2emo = {}
    with open(os.path.join(MVSO_PATH, 'ANP_emotion_scores', 'ANP_emotion_mapping_english.csv'), 'r') as f:
        i = 0
        for line in f.readlines():
            if i == 0:      # header
                header = line.strip().split(',')
                for j in range(1, len(header)):
                    col2emo[j] = header[j]
                i += 1
            else:
                line = line.strip().split(',')
                bc = line[0]
                for j in range(1, len(line)):
                    emotion = col2emo[j]
                    bc2emotion2value[bc][emotion] = float(line[j])
                i += 1

    return bc2emotion2value

def get_MVSO_bc2emo():
    """Filter result of get_MVSO_bc2emotion2value by mapping bc to max emo"""
    bc2emo2val = get_MVSO_bc2emo2val()
    bc2emo = {}
    for bc, emo2val in bc2emo2val.items():
        bc2emo[bc] = max(emo2val.keys(), key=(lambda key: emo2val[key]))
    return bc2emo

def get_MVSO_bc2idx():
    """Return dictionary mapping biconcept to idx"""
    bc2idx = {}
    for i, bc in enumerate(sorted([d for d in os.listdir(MVSO_BC_PATH) if not d.startswith('.')])):
        bc2idx[bc] = i
    return bc2idx

def download_MVSO_imgs(output_dir=os.path.join(MVSO_PATH, 'imgs'), target_w=256, target_h=256):
    """Download, resize, and center crop images"""
    import socket
    socket.setdefaulttimeout(30)

    mr = MovieReader()                  # used to resize and center crop

    def retrieve_img_and_process(url_and_fp):
        url, fp = url_and_fp[0], url_and_fp[1]
        urllib.urlretrieve(url, fp)

        # Reopen image to resize and central crop
        try:
            im = Image.open(fp)
            if im.mode != 'RGB':        # type L, P, etc. shows some type of Flickr unavailable photo img
                os.remove(fp)
                # continue
            im = np.array(im)
            im =  mr.resize_and_center_crop(im, target_w, target_h)
            Image.fromarray(im).save(fp)
        except Exception as e:
            # print url
            # print e
            pass

    # import time

    urls = []
    fps = []
    with open(os.path.join(MVSO_PATH, 'image_url_mappings', 'english.csv'), 'r') as f:
        i = 0
        for line in f.readlines():
            if i == 0:      # skip header
                i += 1
                continue
            else:
                if i < 3121850:
                    i += 1
                    continue
                bc, url = line.strip().split(',')
                bc_dir = os.path.join(output_dir, bc)

                # if i % 50 == 0:
                    # time.sleep(0.1)
                    # print 'bi_concept: {}; num_imgs: {}'.format(bc, i)
                i += 1

                # Make bi_concept directory if it doesn't exist
                if not os.path.exists(bc_dir):
                    os.makedirs(bc_dir)

                # Retrive image and save
                fn = os.path.basename(url)
                fp = os.path.join(bc_dir, fn)

                # Skip if file exists
                if os.path.exists(fp):
                    continue

                # Old sequential way:
                # retrieve_img_and_process([url, fp])

                urls.append(url)
                fps.append(fp)
    print 'done getting urls'

    from multiprocessing.dummy import Pool as ThreadPool
    pool = ThreadPool(100)
    urls_and_fps = zip(urls, fps)
    for i in range(0, len(urls), 1000):
        print i
        results = pool.map(retrieve_img_and_process, urls_and_fps[i:i+1000])

########################################################################################################################
# Sentibank + MVSO
########################################################################################################################

# Helper that just wraps dataset-specific functions
def get_bc2sent(dataset):
    if dataset == 'Sentibank':
        return get_Sentibank_bc2sent()
    elif dataset == 'MVSO':
        return get_MVSO_bc2sent()
    else:
        print 'unknown dataset: {}'.format(dataset)

def get_bc2emo(dataset):
    if dataset == 'Sentibank':
        return get_Sentibank_bc2emo()
    elif dataset == 'MVSO':
        return get_MVSO_bc2emo()
    else:
        print 'unknown dataset: {}'.format(dataset)

def get_bc2idx(dataset):
    if dataset == 'Sentibank':
        return get_Sentibank_bc2idx()
    elif dataset == 'MVSO':
        return get_MVSO_bc2idx()
    else:
        print 'unknown dataset: {}'.format(dataset)

# Writing images to tfrecords
def write_VSO_to_tfrecords(dataset, split=[0.8, 0.1, 0.1]):
    """Create tfrecord file for each biconcept for train,valid,test"""
    def _bytes_feature(value):
        return tf.train.Feature(bytes_list=tf.train.BytesList(value=[value]))

    def _int64_feature(value):
        return tf.train.Feature(int64_list=tf.train.Int64List(value=[value]))

    def _float_feature(value):
        return tf.train.Feature(float_list=tf.train.FloatList(value=[value]))

    # Get lookups for each objective in order to label
    bc2sent = get_bc2sent(dataset)
    bc2emo = get_bc2emo(dataset)
    bc2idx = get_bc2idx(dataset)

    # Read config for sent_neutral_absval
    __location__ = os.path.realpath(os.path.join(os.getcwd(), os.path.dirname(__file__)))
    config = read_yaml(os.path.join(__location__, 'config.yaml'))
    sent_neutral_absval = config['sent_neutral_absval']

    # Iterate over biconcept folders
    if dataset == 'Sentibank':
         bc_path = SENTIBANK_BC_PATH
         dataset_path = SENTIBANK_FLICKR_PATH
    elif dataset == 'MVSO':
        bc_path = MVSO_BC_PATH
        dataset_path = MVSO_PATH
    else:
        print 'unknown dataset: {}'.format(dataset)

    for bc in [d for d in os.listdir(bc_path) if not d.startswith('.')]:
        print bc

        # Get filepaths of each image
        cur_bc_path = os.path.join(bc_path, bc)
        img_fns = [f for f in os.listdir(cur_bc_path) if f.endswith('jpg')]
        img_fps = [os.path.join(cur_bc_path, fn) for fn in img_fns]

        # Make directory for tfrecords - train, valid, test
        if not os.path.exists(os.path.join(dataset_path, 'tfrecords')):
            os.mkdir(os.path.join(dataset_path, 'tfrecords'))
        for name in ['train', 'valid', 'test']:
            if not os.path.exists(os.path.join(dataset_path, 'tfrecords', name)):
                os.mkdir(os.path.join(dataset_path, 'tfrecords', name))

        # Get tfrecord filepath and writer ready
        tfrecords_filename = '{}.tfrecords'.format(bc)
        tr_tfrecords_fp = os.path.join(dataset_path, 'tfrecords', 'train', tfrecords_filename)
        va_tfrecords_fp = os.path.join(dataset_path, 'tfrecords', 'valid', tfrecords_filename)
        te_tfrecords_fp = os.path.join(dataset_path, 'tfrecords', 'test', tfrecords_filename)
        tr_writer = tf.python_io.TFRecordWriter(tr_tfrecords_fp)
        va_writer = tf.python_io.TFRecordWriter(va_tfrecords_fp)
        te_writer = tf.python_io.TFRecordWriter(te_tfrecords_fp)
        train_endidx = int(split[0] * len(img_fps))
        valid_endidx = train_endidx + int(split[1] * len(img_fps))

        # Convert images to tfrecord Examples
        for i, img_fp in enumerate(img_fps):
            try:
                # Pull out image and labels and make example
                img = Image.open(img_fp)
                if img.mode != 'RGB' or img.format != 'JPEG':   # e.g. black and white (mode == 'L')
                    continue
                img = np.array(img)

                id = bc + '-' + os.path.basename(img_fp).split('.')[0]
                h, w = img.shape[0], img.shape[1]
                img_raw = img.tostring()
                # Can't use None as a feature, so just pass in a dummmy value. It'll be skipped anyway
                sent_reg_label = get_label(dataset, bc, 'sent_reg', bc_lookup=bc2sent)
                sent_reg_label = sent_reg_label if sent_reg_label else 0.0
                sent_biclass_label = get_label(dataset, bc, 'sent_biclass', bc_lookup=bc2sent, sent_neutral_absval=sent_neutral_absval)
                sent_biclass_label = sent_biclass_label if sent_biclass_label else 0
                sent_triclass_label = get_label(dataset, bc, 'sent_triclass', bc_lookup=bc2sent, sent_neutral_absval=sent_neutral_absval)
                sent_triclass_label = sent_triclass_label if sent_triclass_label else 0
                emo_label = get_label(dataset, bc, 'emo', bc_lookup=bc2emo)
                emo_label = emo_label if emo_label else 0
                bc_label = get_label(dataset, bc, 'bc', bc_lookup=bc2idx)
                bc_label = bc_label if bc_label else 0

                example = tf.train.Example(features=tf.train.Features(feature={
                    'id': _bytes_feature(id),
                    'h': _int64_feature(h),
                    'w': _int64_feature(w),
                    'img': _bytes_feature(img_raw),
                    'sent_reg': _float_feature(sent_reg_label),
                    'sent_biclass': _int64_feature(sent_biclass_label),
                    'sent_triclass': _int64_feature(sent_triclass_label),
                    'emo': _int64_feature(emo_label),
                    'bc': _int64_feature(bc_label)}))

                # Figure out which writer to use (train, valid, test)
                if i < train_endidx:
                    writer = tr_writer
                elif i >= train_endidx and i < valid_endidx:
                    writer = va_writer
                else:
                    writer = te_writer

                writer.write(example.SerializeToString())

            except Exception as e:
                print img_fp, e

    tr_writer.close()
    va_writer.close()
    te_writer.close()

# Writing images to tfrecords
def VSO_bc_class_to_tfrecords(dataset, split=[0.8, 0.1, 0.1], min_bc_cs=120):
    """
    Create tfrecord files for train,valid,test for the task of bc classification. In debugging the classification,
    I believe that there may not be enough shuffling, since the previously saved tfrecords from the above
    function are for each bc, e.g. bright_sun.tfrecords. Therefore, string_input_producer shuffles the files,
    but each batch will only contain records from x bc's. Therefore, we want to make tfrecords 0.tfrecords, 1.tfrecords,
    etc. that say each contain 10,000 images. This still won't be 'perfect' shuffling, but it'll be better.
    """
    # Set dataset
    if dataset == 'Sentibank':
         bc_path = SENTIBANK_BC_PATH
         dataset_path = SENTIBANK_FLICKR_PATH
    elif dataset == 'MVSO':
        bc_path = MVSO_BC_PATH
        dataset_path = MVSO_PATH
    else:
        print 'unknown dataset: {}'.format(dataset)

    # Functions for writing tfrecords
    def _bytes_feature(value):
        return tf.train.Feature(bytes_list=tf.train.BytesList(value=[value]))

    def _int64_feature(value):
        return tf.train.Feature(int64_list=tf.train.Int64List(value=[value]))

    def _float_feature(value):
        return tf.train.Feature(float_list=tf.train.FloatList(value=[value]))

    # Make directory to hold new tfrecords
    new_tfrecords_path = os.path.join(dataset_path, 'tfrecords_bc')
    if not os.path.exists(new_tfrecords_path):
        os.mkdir(new_tfrecords_path)
    for split in ['train', 'valid', 'test']:
        if not os.path.exists(os.path.join(new_tfrecords_path, split)):
            os.mkdir(os.path.join(new_tfrecords_path, split))

    # Note: probably would be faster to read images from existing tfrecords, but I'm not sure the best way to shuffle
    # them (i.e. would need to store pointer to current index in each bc, re-open that bc tfrecords file, etc.).
    # So, let's just recreate from the images.
    # 1) Get all relevant filepaths (relevant according to bc) for each split
    # 2) Shuffle those filepaths
    # 3) Go through and write for each split
    split2fps = defaultdict(list)
    num_bc = 0

    for bc in [d for d in os.listdir(bc_path) if not d.startswith('.')]:
        # Get filepaths of each image
        cur_bc_path = os.path.join(bc_path, bc)
        img_fns = [f for f in os.listdir(cur_bc_path) if f.endswith('jpg')]
        img_fps = [os.path.join(cur_bc_path, fn) for fn in img_fns]

        # Split if not enough images
        if len(img_fps) < min_bc_cs:
            continue
        else:
            train_endidx = int(split[0] * len(img_fps))
            valid_endidx = train_endidx + int(split[1] * len(img_fps))
            split2fps['train'].extend(img_fps[0:train_endidx])
            split2fps['valid'].extend(img_fps[train_endidx:valid_endidx])
            split2fps['test'].extend(img_fps[valid_endidx:])
            num_bc += 1

    # Print some things
    for split, fps in split2fps.items():
        print split, len(fps)
    print 'Number bc with enough images: {}'.format(num_bc)

    # Get lookups for each objective in order to label
    bc2idx = get_bc2idx(dataset)

    # Go through each split, shuffle img fps, and try to write example
    for split, fps in split2fps.items():
        num_imgs_added = 0
        tfrecords_fp = os.path.join(new_tfrecords_path, split, '0.tfrecords')
        writer = tf.python_io.TFRecordWriter(tfrecords_fp)

        print tfrecords_fp
        # Shuffle fps to mix up bc's
        random.shuffle(fps)

        for img_fp in fps:
            try:
                # Get image
                img = Image.open(img_fp)
                if img.mode != 'RGB' or img.format != 'JPEG':   # e.g. black and white (mode == 'L')
                    continue
                img = np.array(img)

                bc = os.path.dirname(img_fp).split('/')[-1]
                img_id = os.path.basename(img_fp).split('.')[0]
                id = bc + '/' + img_id
                h, w = img.shape[0], img.shape[1]
                bc_label = get_label(dataset, bc, 'bc', bc_lookup=bc2idx)
                img_raw = img.tostring()

                example = tf.train.Example(features=tf.train.Features(feature={
                    'id': _bytes_feature(id),
                    'h': _int64_feature(h),
                    'w': _int64_feature(w),
                    'img': _bytes_feature(img_raw),
                    'bc': _int64_feature(bc_label)}))
                writer.write(example.SerializeToString())

                num_imgs_added += 1
                # Update tfrecords file
                if (num_imgs_added % 10000 == 0):
                    print 'Split: {}, num_imgs_added: {}'.format(split, num_imgs_added)
                    writer.close()
                    tfrecords_fp = os.path.join(new_tfrecords_path, split, '{}.tfrecords'.format(num_imgs_added / 10000))
                    writer = tf.python_io.TFRecordWriter(tfrecords_fp)
            except Exception as e:
                print img_fp, e

def precompute_and_save_bc_VSO_stats(dataset):
    """
    Save split2n, mean (train), std (train), num_bc_classes, bc_labelidx2filteredidx for use in datasets.py
    NOTE: could've saved all these while originally saving tfrecords in above function...
    """
    # Set dataset
    if dataset == 'Sentibank':
         bc_path = SENTIBANK_BC_PATH
         dataset_path = SENTIBANK_FLICKR_PATH
    elif dataset == 'MVSO':
        bc_path = MVSO_BC_PATH
        dataset_path = MVSO_PATH
    else:
        print 'unknown dataset: {}'.format(dataset)

    bc_tfrecords_path = os.path.join(dataset_path, 'tfrecords_bc')

    split2n = defaultdict(int)
    bc_classes = set()
    mean = np.zeros(3)
    std = np.zeros(3)

    for split in ['train', 'valid', 'test']:
        split_path = os.path.join(bc_tfrecords_path, split)
        for record_fn in os.listdir(split_path):
            record_fp = os.path.join(split_path, record_fn)
            it = tf.python_io.tf_record_iterator(path=record_fp)
            print record_fp
            for str_record in it:
                split2n[split] += 1

                example = tf.train.Example()
                example.ParseFromString(str_record)
                id = (example.features.feature['id'].bytes_list.value[0])
                bc = id.split('/')[0]
                label = (example.features.feature['bc'].int64_list.value[0])
                bc_classes.add((bc, label))

                # Calculate mean and std on training set
                if split == 'train':
                    img_str = (example.features.feature['img'].bytes_list.value[0])
                    img_1d = np.fromstring(img_str, dtype=np.uint8)
                    height = int(example.features.feature['h'].int64_list.value[0])
                    width = int(example.features.feature['w'].int64_list.value[0])
                    reconstructed_img = img_1d.reshape((height, width, 3))
                    reconstructed_img = reconstructed_img.astype(np.float32) / (256.0)   # convert to [0,1)

                    # Running average: new average = old average * (n-c)/n + sum of new value/n).
                    # Where n = total count, m = count in this update
                    img_mean, img_std = np.zeros(3), np.zeros(3)
                    for c in range(3):
                        img_mean[c] = reconstructed_img[:,:,c].mean()
                        img_std[c] = reconstructed_img[:,:,c].std()
                    n = split2n['train']
                    mean = (mean * (n-1) / float(n)) + (img_mean / float(n))
                    std = (std * (n-1) / float(n)) + (img_std / float(n))

    # Finish calculating
    num_bc_classes = len(bc_classes)
    bc_labelidx2filteredidx = {}
    for i, bc_label in enumerate(bc_classes):
        bc_labelidx2filteredidx[int(bc_label[1])] = i

    # Print stats
    print bc_labelidx2filteredidx
    print split2n
    print mean
    print std
    print num_bc_classes

    # Save
    with open(os.path.join(bc_tfrecords_path, 'split2n.pkl'), 'wb') as f:
        pickle.dump(split2n, f, protocol=2)
    with open(os.path.join(bc_tfrecords_path, 'mean.pkl'), 'wb') as f:
        pickle.dump(mean, f, protocol=2)
    with open(os.path.join(bc_tfrecords_path, 'std.pkl'), 'wb') as f:
        pickle.dump(std, f, protocol=2)
    with open(os.path.join(bc_tfrecords_path, 'num_bc_classes.pkl'), 'wb') as f:
        pickle.dump(num_bc_classes, f, protocol=2)
    with open(os.path.join(bc_tfrecords_path, 'bc_labelidx2filteredidx.pkl'), 'wb') as f:
        pickle.dump(bc_labelidx2filteredidx, f, protocol=2)

# Writing images to tfrecords
def write_VSO_biclass_to_tfrecords(dataset, split=[0.8, 0.1, 0.1], sent_neutral_absval=0.5):
    """
    To more appropriately shuffle data, create 0.tfrecords, 1.tfrecords, etc. instead of <bc>.tfrecords.
    """
    def _bytes_feature(value):
        return tf.train.Feature(bytes_list=tf.train.BytesList(value=[value]))

    def _int64_feature(value):
        return tf.train.Feature(int64_list=tf.train.Int64List(value=[value]))

    def _float_feature(value):
        return tf.train.Feature(float_list=tf.train.FloatList(value=[value]))

    # Iterate over biconcept folders
    if dataset == 'Sentibank':
         bc_path = SENTIBANK_BC_PATH
         dataset_path = SENTIBANK_FLICKR_PATH
    elif dataset == 'MVSO':
        bc_path = MVSO_BC_PATH
        dataset_path = MVSO_PATH
    else:
        print 'unknown dataset: {}'.format(dataset)

    # Make directory to hold new tfrecords
    new_tfrecords_path = os.path.join(dataset_path, 'tfrecords_biclass')
    if not os.path.exists(new_tfrecords_path):
        os.mkdir(new_tfrecords_path)
    for split_name in ['train', 'valid', 'test']:
        if not os.path.exists(os.path.join(new_tfrecords_path, split_name)):
            os.mkdir(os.path.join(new_tfrecords_path, split_name))


    # Get lookups for each objective in order to label
    bc2sent = get_bc2sent(dataset)

    # 1) Get all relevant filepaths (relevant according to bc) for each split
    # 2) Shuffle those filepaths
    # 3) Go through and write for each split
    split2fps = defaultdict(list)
    for bc in [d for d in os.listdir(bc_path) if not d.startswith('.')]:
        if bc in bc2sent:
            sent = bc2sent[bc]
            if (sent < -1 * sent_neutral_absval) or (sent > sent_neutral_absval):

                # Get filepaths of each image
                cur_bc_path = os.path.join(bc_path, bc)
                img_fns = [f for f in os.listdir(cur_bc_path) if f.endswith('jpg')]
                img_fps = [os.path.join(cur_bc_path, fn) for fn in img_fns]

                train_endidx = int(split[0] * len(img_fps))
                valid_endidx = train_endidx + int(split[1] * len(img_fps))
                split2fps['train'].extend(img_fps[0:train_endidx])
                split2fps['valid'].extend(img_fps[train_endidx:valid_endidx])
                split2fps['test'].extend(img_fps[valid_endidx:])

    # Go through each split, shuffle img fps, and try to write example
    split2n = defaultdict(int)
    mean = np.zeros(3)
    std = np.zeros(3)
    for split, fps in split2fps.items():
        tfrecords_fp = os.path.join(new_tfrecords_path, split, '0.tfrecords')
        writer = tf.python_io.TFRecordWriter(tfrecords_fp)

        print tfrecords_fp
        # Shuffle fps to mix up bc's
        random.shuffle(fps)

        for img_fp in fps:
            try:
                # Get image
                img = Image.open(img_fp)
                if img.mode != 'RGB' or img.format != 'JPEG':   # e.g. black and white (mode == 'L')
                    continue
                img = np.array(img)

                # Extract info
                bc = os.path.dirname(img_fp).split('/')[-1]
                img_id = os.path.basename(img_fp).split('.')[0]
                id = bc + '/' + img_id
                h, w = img.shape[0], img.shape[1]
                img_raw = img.tostring()
                sent_biclass_label = get_label(dataset, bc, 'sent_biclass', bc_lookup=bc2sent, sent_neutral_absval=sent_neutral_absval)
                # sent_biclass_label = sent_biclass_label if sent_biclass_label else 0

                grayscale_hist = np.array(get_grayscale_hist(img, bins=64)).tostring()
                color_hist = np.array(get_color_hist(img, bins=64)).tostring()

                # Write example
                example = tf.train.Example(features=tf.train.Features(feature={
                    'id': _bytes_feature(id),
                    'h': _int64_feature(h),
                    'w': _int64_feature(w),
                    'img': _bytes_feature(img_raw),
                    'grayscale_hist': _bytes_feature(grayscale_hist),
                    'color_hist': _bytes_feature(color_hist),
                    'sent_biclass': _int64_feature(sent_biclass_label)}))
                writer.write(example.SerializeToString())

                # Update
                split2n[split] += 1

                # Running average: new average = old average * (n-c)/n + sum of new value/n).
                # Where n = total count, m = count in this update
                if split == 'train':
                    img_mean, img_std = np.zeros(3), np.zeros(3)
                    for c in range(3):
                        img_mean[c] = (img[:,:,c] / 256.0).mean()
                        img_std[c] = (img[:,:,c] / 256.0).std()
                    n = split2n['train']
                    mean = (mean * (n-1) / float(n)) + (img_mean / float(n))
                    std = (std * (n-1) / float(n)) + (img_std / float(n))

                # Update tfrecords file
                if (split2n[split] % 10000 == 0):
                    print 'Split: {}, num_imgs_added: {}'.format(split, split2n[split])
                    writer.close()
                    tfrecords_fp = os.path.join(new_tfrecords_path, split, '{}.tfrecords'.format(split2n[split] / 10000))
                    writer = tf.python_io.TFRecordWriter(tfrecords_fp)

            except Exception as e:
                print img_fp, e

    # Print stats
    print split2n
    print mean
    print std

    # Save
    with open(os.path.join(new_tfrecords_path, 'split2n.pkl'), 'wb') as f:
        pickle.dump(split2n, f, protocol=2)
    with open(os.path.join(new_tfrecords_path, 'mean.pkl'), 'wb') as f:
        pickle.dump(mean, f, protocol=2)
    with open(os.path.join(new_tfrecords_path, 'std.pkl'), 'wb') as f:
        pickle.dump(std, f, protocol=2)

def get_label(dataset, bc, obj, bc_lookup=None, sent_neutral_absval=None):
    """
    Return label from bi_concept string according to the objective (sentiment, emotion, biconcept)

    Handful of cases for sent where label doesn't exist. For example, candid_guy
    """
    if obj == 'sent_reg':
        if bc in bc_lookup:
            return bc_lookup[bc]
        else:
            return None
    elif obj == 'sent_biclass' or obj == 'sent_triclass':
        if bc in bc_lookup:
            return map_label_to_int(dataset, bc_lookup[bc], obj, sent_neutral_absval=sent_neutral_absval)
        else:
            return None
    elif obj == 'emo':
        if dataset == 'Sentibank':
            if len(bc_lookup[bc]) > 0:
                # TODO: what if there's a tie? (e.g. anger: 1, fear: 1) (this is probably pretty common)
                emo = bc_lookup[bc].most_common(1)[0][0]    # list of tuples of most occurring elements
                # print bc, emo, map_label_to_int(emo, obj)
                return map_label_to_int(dataset, emo, obj)
            else:       # no emotions for biconcept
                return None
        elif dataset == 'MVSO':
            if bc in bc_lookup:
                return map_label_to_int(dataset, bc_lookup[bc], obj)
            else:
                return None
        else:
            print 'unknown dataset: {}'.format(dataset)
    elif obj == 'bc':
        return map_label_to_int(dataset, bc, obj, bc2idx=bc_lookup)

def map_label_to_int(dataset, label, obj, sent_neutral_absval=None, bc2idx=None):
    """Map emo and bc string labels to int for classification tasks"""
    if obj == 'sent_biclass':
        label = 'neg' if label < 0 else 'pos'
        d = {'neg': 0, 'pos': 1}
        return SENT_BICLASS_LABEL2INT[label]
    elif obj == 'sent_triclass':
        if label > sent_neutral_absval:
            label = 'pos'
        elif label < -1 * sent_neutral_absval:
            label = 'neg'
        else:
            label = 'neutral'
        return SENT_TRICLASS_LABEL2INT[label]
    elif obj == 'emo':
        if dataset == 'Sentibank':
            return SENTIBANK_EMO_LABEL2INT[label]
        elif dataset == 'MVSO':
            return MVSO_EMO_LABEL2INT[label]
        else:
            print 'unknown dataset: {}'.format(dataset)
    elif obj == 'bc':
        return bc2idx[label]

def get_all_VSO_img_fps(dataset):
    """Return dictionary mapping bi_concept to list of img file paths"""
    path = SENTIBANK_BC_PATH if dataset == 'Sentibank' else os.path.join(MVSO_PATH, 'imgs')

    bc2img_fps = {}
    for bc in [d for d in os.listdir(path) if not d.startswith('.')]:
        cur_bc_path = os.path.join(path, bc)
        img_fns = [f for f in os.listdir(cur_bc_path) if f.endswith('jpg')]
        img_fps = [os.path.join(cur_bc_path, fn) for fn in img_fns]
        bc2img_fps[bc] = img_fps

    return bc2img_fps

def move_bad_jpgs(dataset):
    """Move bad jpegs out of biconcept folders using bad jpgs from remove_corrupted.lua"""
    if dataset == 'Sentibank':
         # Make directory to store bad jpgs
        bad_jpgs_dir = os.path.join(SENTIBANK_FLICKR_PATH, 'bad_jpgs')
        if not os.path.exists(bad_jpgs_dir):
            os.mkdir(bad_jpgs_dir)

        bad_jpg_fns = open(os.path.join(SENTIBANK_FLICKR_PATH, 'bad_imgs.txt'), 'r').readlines()
        bad_jpg_fns = [f.strip('\n') for f in bad_jpg_fns]

        bc2img_fps = get_all_VSO_img_fps(dataset)
        for bc, img_fps in bc2img_fps.items():
            print bc
            for img_fp in img_fps:
                img_fn = os.path.basename(img_fp)
                if img_fn in bad_jpg_fns:
                    print bc, img_fn
                    os.rename(img_fp, os.path.join(bad_jpgs_dir, '{}-{}'.format(bc, img_fn)))
    elif dataset == 'MVSO':
        print 'MVSO not impelemented yet'
    else:
        print 'unknown dataset: {}'.format(dataset)

def save_bc_channel_mean_std(dataset):
    """Save channel-wise mean and stddev so we can standardize"""
    # Make directory to save
    if dataset == 'Sentibank':
        out_dir = os.path.join(SENTIBANK_FLICKR_PATH, 'bc_channelmeanstd')
    else:
        out_dir = os.path.join(MVSO_PATH, 'bc_channelmeanstd')
    if not os.path.exists(out_dir):
        os.mkdir(out_dir)

    bc2mean = {}
    bc2std = {}

    bc2img_fps = get_all_VSO_img_fps(dataset)
    for bc, img_fps in bc2img_fps.items():
        mean, std = np.zeros(3), np.zeros(3)
        n = 0
        for img_fp in img_fps:
            try:
                im = Image.open(img_fp)
                if im.mode != 'RGB':      # type L, P, etc. shows some type of Flickr unavailable photo img
                    os.remove(img_fp)
                    continue
                im = np.array(im)
                im = im.astype(np.float32)
                im /= 256.0               # convert to [0,)
                for c in range(3):
                    mean[c] += im[:,:,c].mean()
                    std[c] += im[:,:,c].std()
                n += 1
            except Exception as e:
                print e

        mean /= float(n)
        std /= float(n)
        print '{} mean: {}'.format(bc, mean)
        print '{} std: {}'.format(bc, std)

        bc2mean[bc] = mean
        bc2std[bc] = std

    with open(os.path.join(out_dir, 'bc2channelmean.pkl'.format(bc)), 'w') as f:
        pickle.dump(bc2mean, f, protocol=2)
    with open(os.path.join(out_dir, 'bc2channelstd.pkl'.format(bc)), 'w') as f:
        pickle.dump(bc2std, f, protocol=2)

########################################################################################################################
# You image emotion
########################################################################################################################
def _get_you_imemo_urls():
    """
    Return URLs for images where majority of 5 (most of the time it's 5) AMT reviewers agreed with the emotion label

    Stats
    -----
    Total 23166
    excitement 2918
    sadness 2902
    contentment 5356
    disgust 1650
    anger 1255
    awe 3133
    fear 1029
    amusement 4923
    """
    csv_fns = [f for f in os.listdir(YOU_IMEMO_PATH) if f.endswith('csv')]
    emo2urls = defaultdict(list)
    for fn in csv_fns:
        emo = fn.split('_')[0]
        fp = os.path.join(YOU_IMEMO_PATH, fn)
        with open(fp) as f:
            for line in f.readlines():
                _, url, disagree, agree = line.split(',')
                if int(agree) > int(disagree):
                    emo2urls[emo].append(url)
    return emo2urls

def retrieve_you_imemo_imgs(out_dir=os.path.join(YOU_IMEMO_PATH, 'imgs')):
    """Download images for each emotion for You im_emo dataset"""
    emo2urls = _get_you_imemo_urls()
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
    for emo, urls in emo2urls.items():
        print emo
        if emo != 'fear' and emo != 'amusement':
            continue
        emo_dir = os.path.join(out_dir, emo)
        if not os.path.exists(emo_dir):
            os.makedirs(emo_dir)
        for url in urls:
            img_name = os.path.basename(url)
            urllib.urlretrieve(url, os.path.join(emo_dir, img_name))

########################################################################################################################
# Plutchik's wheel of emotions and color
########################################################################################################################
def save_plutchik_color_imgs():
    """Parse txt file with emotions and RGB colors, save solid color images"""
    # label2rgb = {}
    with open(os.path.join(PLUTCHIK_PATH, 'plutchik_colors.txt'), 'r') as f:
        for i, line in enumerate(f.readlines()):
            m = re.match(r'(\w+) - R: (\w+) G: (\w+) B: (\w+)', line)
            label, r, g, b = m.group(1), m.group(2), m.group(3), m.group(4)
            print i, line, r, g, b
            # label2rgb[label] = [r,g,b]
            im = np.zeros([256, 256, 3], 'uint8')
            im[:,:,0] = np.ones([256, 256]) * int(r)
            im[:,:,1] = np.ones([256, 256]) * int(g)
            im[:,:,2] = np.ones([256, 256]) * int(b)

            import scipy.misc
            scipy.misc.imsave(os.path.join(PLUTCHIK_PATH, '{}_{}.jpg'.format(i, label)), im)

########################################################################################################################
# AVA
########################################################################################################################
def ava_to_tfrecords(delta=0.67, split=[0.8,0.1,0.1]):
    """
    Write AVA images

    Parameters
    ----------
    delta: delta to ignore neutral items
        items < (5-delta) are negative, items > (5+delta) are positive
    split: percent of train, valid, test
    """
    NUM_IMGS_PER_TFRECORD = 1000

    import sys
    # Add this to path so that files within vislab can import vislab
    sys.path.insert(0,  os.path.realpath('core/ext_libs'))
    from core.ext_libs.vislab.datasets import ava

    # Load dataframe
    print 'Loading AVA df'
    df = ava.get_ava_df()

    # Ignore 'neutral' items
    df = df[(df.rating_mean < (5.0 - delta)) | (df.rating_mean > (5.0 + delta))]

    # Add labels
    def label_f(x, bin_edges):
        for i in range(len(bin_edges)):
            if x < bin_edges[i]:
                return int(i-1)
    bin_edges = [0, 5.0, 10.0]
    df['label'] = df.rating_mean.apply(label_f, args=(bin_edges, ))


    # Get id to labels
    print 'Getting id2label'
    id2label = {}
    for id, row in df.iterrows():
        id2label[id] = row.label

    # Make tfrecords dir
    out_dir = 'tfrecords_{}'.format(delta)
    out_dirpath = os.path.join(AVA_PATH, out_dir)
    if not os.path.exists(out_dirpath):
        os.mkdir(out_dirpath)
    for name in ['train', 'valid', 'test']:
        if not os.path.exists(os.path.join(out_dirpath, name)):
            os.mkdir(os.path.join(out_dirpath, name))

    # Write tfrecords
    # Get tfrecord filepath and writer ready
    def get_writers(i):
        tfrecords_filename = '{}.tfrecords'.format(i)
        tr_tfrecords_fp = os.path.join(out_dirpath, 'train', tfrecords_filename)
        va_tfrecords_fp = os.path.join(out_dirpath, 'valid', tfrecords_filename)
        te_tfrecords_fp = os.path.join(out_dirpath, 'test', tfrecords_filename)
        tr_writer = tf.python_io.TFRecordWriter(tr_tfrecords_fp)
        va_writer = tf.python_io.TFRecordWriter(va_tfrecords_fp)
        te_writer = tf.python_io.TFRecordWriter(te_tfrecords_fp)
        return tr_writer, va_writer, te_writer

    def _bytes_feature(value):
        return tf.train.Feature(bytes_list=tf.train.BytesList(value=[value]))

    def _int64_feature(value):
        return tf.train.Feature(int64_list=tf.train.Int64List(value=[value]))

    tr_writer, va_writer, te_writer = get_writers(0)
    imgs_dirpath = os.path.join(AVA_PATH, 'images')
    i = 0
    label2count = defaultdict(int)
    for fn in os.listdir(imgs_dirpath):
        if i % 1000 == 0:
            print i, label2count

        id = fn.split('.jpg')[0]
        img_fp = os.path.join(imgs_dirpath, fn)

        try:
            # Pull out image and labels and make example
            img = Image.open(img_fp)
            if img.mode != 'RGB' or img.format != 'JPEG':   # e.g. black and white (mode == 'L')
                continue
            img = np.array(img)
            h, w = img.shape[0], img.shape[1]

            if (h < 256) or (w < 256):
                print 'width or height too small'
                continue

            img_raw = img.tostring()
            label = int(id2label[id])

            example = tf.train.Example(features=tf.train.Features(feature={
                'id': _bytes_feature(id),
                'h': _int64_feature(h),
                'w': _int64_feature(w),
                'img': _bytes_feature(img_raw),
                'sent_biclass': _int64_feature(label)}))

            if (i % NUM_IMGS_PER_TFRECORD) < (split[0] * NUM_IMGS_PER_TFRECORD):
                writer = tr_writer
            elif (i % NUM_IMGS_PER_TFRECORD) < ((split[0]+split[1]) * NUM_IMGS_PER_TFRECORD):
                writer = va_writer
            else:
                writer = te_writer

            if (i % NUM_IMGS_PER_TFRECORD) == 0:
                tr_writer, va_writer, te_writer = get_writers(i / NUM_IMGS_PER_TFRECORD)

            writer.write(example.SerializeToString())

            # Update given no exceptions
            label2count[label] += 1
            i += 1

        except Exception as e:
            pass

    print label2count
    with open(os.path.join(AVA_PATH, 'delta_{}_label2count.json'.format(delta)), 'wb') as fp:
        json.dump(label2count, fp)

def save_ava_n_channel_mean_std(delta=0.67):
    """Save channel-wise mean and stddev so we can standardize"""
    split2n, mean, std = defaultdict(int), np.zeros(3), np.zeros(3)

    # Make directory to save
    out_dir = os.path.join(AVA_PATH, 'n_channelmeanstd')
    if not os.path.exists(out_dir):
        os.mkdir(out_dir)

    # Iterate through tfrecords
    tfrecords_dir = os.path.join(AVA_PATH, 'tfrecords_{}'.format(delta), 'train')
    for tfr in sorted(os.listdir(tfrecords_dir)):
        tfr_path = os.path.join(tfrecords_dir, tfr)
        print tfr_path

        for str_record in tf.python_io.tf_record_iterator(tfr_path):
            split2n['train'] += 1

            example = tf.train.Example()
            example.ParseFromString(str_record)
            img_str = (example.features.feature['img'].bytes_list.value[0])
            img_1d = np.fromstring(img_str, dtype=np.uint8)
            height = int(example.features.feature['h'].int64_list.value[0])
            width = int(example.features.feature['w'].int64_list.value[0])
            reconstructed_img = img_1d.reshape((height, width, 3))
            reconstructed_img = reconstructed_img.astype(np.float32) / (256.0)   # convert to [0,1)

            # Running average: new average = old average * (n-c)/n + sum of new value/n).
            # Where n = total count, m = count in this update
            img_mean, img_std = np.zeros(3), np.zeros(3)
            for c in range(3):
                img_mean[c] = reconstructed_img[:,:,c].mean()
                img_std[c] = reconstructed_img[:,:,c].std()
            n = split2n['train']
            mean = (mean * (n-1) / float(n)) + (img_mean / float(n))
            std = (std * (n-1) / float(n)) + (img_std / float(n))

    # Get n for valid and test
    for split in ['valid', 'test']:
        tfrecords_dir = os.path.join(AVA_PATH, 'tfrecords_{}'.format(delta), split)
        for tfr in sorted(os.listdir(tfrecords_dir)):
            tfr_path = os.path.join(tfrecords_dir, tfr)
            for str_record in tf.python_io.tf_record_iterator(tfr_path):
                split2n[split] += 1

    print 'split2n: {}'.format(split2n)
    print 'mean: {}'.format(mean)
    print 'std: {}'.format(std)

    with open(os.path.join(out_dir, 'split2n.pkl'), 'wb') as f:
        pickle.dump(split2n, f, protocol=2)
    with open(os.path.join(out_dir, 'channelmean.pkl'), 'wb') as f:
        pickle.dump(mean, f, protocol=2)
    with open(os.path.join(out_dir, 'channelstd.pkl'), 'wb') as f:
        pickle.dump(std, f, protocol=2)

if __name__ == '__main__':

    # Set up commmand line arguments
    parser = argparse.ArgumentParser(description='Download and process data')
    parser.add_argument('--MVSO_dl_imgs', dest='MVSO_dl_imgs', action='store_true')
    parser.add_argument('--MVSO_bc2emo2val', dest='MVSO_bc2emo2val', action='store_true')
    parser.add_argument('--VSO_dataset', dest='VSO_dataset', default='Sentibank', help='Sentibank,MVSO')
    parser.add_argument('--VSO_img_fps', dest='VSO_img_fps', action='store_true')
    parser.add_argument('--bc2sent', dest='bc2sent', action='store_true')
    parser.add_argument('--bc2emo', dest='bc2emo', action='store_true')
    parser.add_argument('--bc2idx', dest='bc2idx', action='store_true')
    parser.add_argument('--VSO_to_tfrecords', dest='VSO_to_tfrecords', action='store_true')
    parser.add_argument('--VSO_bc_class_to_tfrecords', dest='VSO_bc_class_to_tfrecords', action='store_true')
    parser.add_argument('--precompute_and_save_bc_VSO_stats', dest='precompute_and_save_bc_VSO_stats', action='store_true')
    parser.add_argument('--write_VSO_biclass_to_tfrecords', dest='write_VSO_biclass_to_tfrecords', action='store_true')
    parser.add_argument('--move_bad_jpgs', dest='move_bad_jpgs', action='store_true')
    parser.add_argument('--bc_channel_mean_std', dest='bc_channel_mean_std', action='store_true')
    parser.add_argument('--you_dl_imgs', dest='you_dl_imgs', action='store_true')
    parser.add_argument('--save_plutchik_color_imgs', dest='save_plutchik_color_imgs', action='store_true')
    parser.add_argument('--ava_to_tfrecords', dest='ava_to_tfrecords', action='store_true')
    parser.add_argument('--save_ava_n_channel_mean_std', dest='save_ava_n_channel_mean_std', action='store_true')

    cmdline = parser.parse_args()

    if cmdline.MVSO_dl_imgs:
        download_MVSO_imgs()
    elif cmdline.MVSO_bc2emo2val:
        pprint(get_MVSO_bc2emo2val())
    elif cmdline.VSO_img_fps:
        bc2img_fps = get_all_VSO_img_fps(cmdline.VSO_dataset)
        print len([k for k, v in bc2img_fps.items() if len(v) > 120])
        print len(bc2img_fps)
    elif cmdline.bc2sent:
        pprint(get_bc2sent(cmdline.VSO_dataset))
    elif cmdline.bc2emo:
        pprint(get_bc2emo(cmdline.VSO_dataset))
    elif cmdline.bc2idx:
        pprint(get_bc2idx(cmdline.VSO_dataset))
    elif cmdline.VSO_to_tfrecords:
        write_VSO_to_tfrecords(cmdline.VSO_dataset)
    elif cmdline.VSO_bc_class_to_tfrecords:
        VSO_bc_class_to_tfrecords(cmdline.VSO_dataset)
    elif cmdline.precompute_and_save_bc_VSO_stats:
        precompute_and_save_bc_VSO_stats(cmdline.VSO_dataset)
    elif cmdline.write_VSO_biclass_to_tfrecords:
        write_VSO_biclass_to_tfrecords(cmdline.VSO_dataset)
    elif cmdline.move_bad_jpgs:
        move_bad_jpgs(cmdline.VSO_dataset)
    elif cmdline.bc_channel_mean_std:
        save_bc_channel_mean_std(cmdline.VSO_dataset)
    elif cmdline.you_dl_imgs:
        retrieve_you_imemo_imgs()
    elif cmdline.save_plutchik_color_imgs:
        save_plutchik_color_imgs()
    elif cmdline.ava_to_tfrecords:
        ava_to_tfrecords()
    elif cmdline.save_ava_n_channel_mean_std:
        save_ava_n_channel_mean_std()